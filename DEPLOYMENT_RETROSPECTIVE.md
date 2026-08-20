# Deployment Retrospective — What Was Actually Built, Step by Step

A complete record of the real deployment process for this project: every AWS resource created, the exact configuration chosen at each step, and how everything connects. Written after the fact, reflecting what actually happened — including the bugs hit and how they were resolved — not an idealized plan.

---

## 1. IAM

**Created**: one IAM **user** (not role) named something like `github-actions-deployer`, with:
- `AmazonEC2ContainerRegistryFullAccess` — lets it push Docker images to ECR
- `AmazonECS_FullAccess` — lets it register task definitions and update services

**Generated**: an access key pair for this user. These two values (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) became GitHub Actions secrets — this is how the CI/CD pipeline authenticates to your AWS account with no manual login step.

**Also required**: the **ECS service-linked role** (`AWSServiceRoleForECS`) — hit a real error here (`Unable to assume the service linked role`) when first creating the cluster. Fixed with:
```bash
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com
```
This is a one-time, per-account setup step, separate from the deployer user above — it's what lets ECS itself (not your IAM user) perform actions on your behalf internally.

**`ecsTaskExecutionRole`**: a separate role, referenced inside `backend-task-def.json`/`frontend-task-def.json` as `executionRoleArn`. This is what each **container** uses at startup to pull its image from ECR and read secrets — distinct from both the deployer user and the service-linked role. Verified it already existed (or was auto-created) rather than built manually.

---

## 2. ECR (Elastic Container Registry)

Created two private repositories:
- `quick-commerce-backend`
- `quick-commerce-frontend`

Settings chosen: **Mutable** tag mutability (since the pipeline reuses the `:latest` tag on every push), **AES-256** encryption (default, no KMS needed).

These are where GitHub Actions pushes every built Docker image — both a commit-SHA tag and a `:latest` tag, on every push to `main`. `:latest` was added specifically after a `CannotPullContainerError` revealed the task definitions referenced an image tag the workflow was never actually producing.

---

## 3. Secrets — GitHub Actions, not AWS Secrets Manager

Originally scoped to use AWS Secrets Manager, but pivoted to **GitHub Actions repository secrets** instead, for simplicity — the workflow renders both task definitions from these secrets via `sed` substitution at deploy time, rather than the task definitions referencing Secrets Manager ARNs directly.

**16 secrets total**, set in GitHub repo → Settings → Secrets:

| Category | Secrets |
|---|---|
| AWS auth | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Database & LLM | `MONGODB_URI`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY` |
| Twilio | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER` |
| Cloudinary | `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` |
| CORS | `CORS_ORIGINS` — **must be a genuine JSON array with quoted strings**, e.g. `["http://...:8501"]`; a bare unquoted `[http://...]` crashed the container on startup in production (`JSONDecodeError`) — this exact mistake happened and cost real debugging time before a `field_validator` was added to `config.py` to auto-correct this specific pattern |
| Admin auth | `ADMIN_WS_TOKEN` — any self-chosen password, shared identically between backend and frontend |
| Frontend → backend URLs | `API_BASE_URL`, `WS_BASE_URL` |

---

## 4. VPC & Networking

**Used the account's default VPC** (`vpc-03641e8cc17fc187b`, `172.31.0.0/16`) — no custom VPC created, deliberately, to keep scope minimal.

**Subnets used**: 2 of the default VPC's auto-created subnets, in **2 different Availability Zones** (a hard NLB requirement):
- `subnet-0040804e37660f0fd` — `us-east-1c`
- `subnet-052efb2f7696e67b9` — `us-east-1e`

These same 2 subnets were reused consistently across every NLB and every ECS service — backend NLB, frontend NLB, backend ECS service, frontend ECS service all reference this identical pair.

**Security Groups created** (2, one per service):
- `quick-commerce-backend-sg` — inbound TCP 8000 and TCP 8001 from `0.0.0.0/0`, outbound all
- `quick-commerce-frontend-sg` — inbound TCP 8501 from `0.0.0.0/0`, outbound all

Each ECS service uses its own security group, attached at service-creation time under **Networking**.

---

## 5. Target Groups (created before the NLBs, since NLB listeners reference them)

3 target groups, all **type: IP** (required for Fargate `awsvpc` networking), all **protocol: TCP** (matching NLB's Layer 4 nature — chosen explicitly over the default HTTP option in the form):

| Name | Port | Health check path |
|---|---|---|
| `backend-api-tg` | 8000 | `/health` |
| `backend-admin-tg` | 8001 | `/health` |
| `frontend-tg` | 8501 | `/_stcore/health` |

No targets manually registered — left empty at creation, since ECS registers the real running task's IP automatically once the service exists and starts.

---

## 6. Network Load Balancers (2)

**`quick-commerce-backend-nlb`**
- Scheme: Internet-facing
- IP type: IPv4
- VPC + the same 2 subnets from step 4
- Security group: `quick-commerce-backend-sg` (had to explicitly swap this in — the form defaulted to the AWS `default` security group, which was wrong)
- **2 listeners**, both had to be manually corrected from the form's default (`TCP:80`, forwarding to nothing real):
  - `TCP:8000` → `backend-api-tg`
  - `TCP:8001` → `backend-admin-tg`

**`quick-commerce-frontend-nlb`**
- Same VPC/subnets/pattern
- Security group: `quick-commerce-frontend-sg`
- **1 listener**: `TCP:8501` → `frontend-tg`

**DNS names** (the actual public entry points):
```
quick-commerce-backend-nlb-0c1896f9be5fe529.elb.us-east-1.amazonaws.com
quick-commerce-frontend-nlb-a61d20f8a96f0f18.elb.us-east-1.amazonaws.com
```

---

## 7. CloudWatch Log Groups

Created manually, **before** the ECS services (task definitions reference these exact names in `logConfiguration`, and registration/startup would fail without them existing first):
```
/ecs/quick-commerce-backend
/ecs/quick-commerce-frontend
```
Settings: **Never expire** retention, **Standard** log class, no KMS, no deletion protection.

---

## 8. ECS Cluster

```bash
aws ecs create-cluster --cluster-name quick-commerce-cluster
```
Infrastructure mode: **Fargate only** (explicitly chosen over "Fargate and Managed/Self-managed Instances," since no EC2 capacity is needed for a single-task-per-service setup).

Hit the IAM service-linked role error here first (see step 1) before this succeeded.

---

## 9. Task Definitions

`backend-task-def.json` and `frontend-task-def.json` live in the repo root, with `__PLACEHOLDER__`-style tokens for every secret value. These are **not** registered manually — the CI/CD workflow renders and registers them automatically on every push to `main`, via `sed` substitution + `aws ecs register-task-definition`.

Backend's `environment` array ended up with roughly a dozen entries (Mongo, Gemini, Groq, OpenAI, Tavily, Twilio ×3, Cloudinary ×3, admin token, CORS origins). Frontend's has 3 (`API_BASE_URL`, `WS_BASE_URL`, `ADMIN_WS_TOKEN`).

Both reference `executionRoleArn` pointing at `ecsTaskExecutionRole` (step 1), and both `image` fields point at the ECR repos from step 2 using the `:latest` tag.

---

## 10. ECS Services (2)

**`quick-commerce-backend-service`**
- Family: `quick-commerce-backend`, Launch type: Fargate, Desired tasks: **1**
- Health check grace period: 60 seconds (gives the container time to boot — Whisper/embedding model pre-download happens at image build time, but Mongo connection + FastAPI startup still take a moment)
- Networking: the 2 default subnets, `quick-commerce-backend-sg`, Public IP on
- **Load balancing required two separate passes**, since the console's Create-service flow only supports one container-port mapping at creation time:
  1. At creation: `backend:8000` → `quick-commerce-backend-nlb` → listener `TCP:8000` → `backend-api-tg`
  2. After creation, via **Update service**, a second "Load balancer" block was added: `backend:8001` → same NLB → listener `TCP:8001` → `backend-admin-tg`
- A mistaken attempt to create a *second, separate* ECS service (`quick-commerce-backend-service-admin`) for the second port was caught and abandoned before creation — that would have split the single-process, dual-port design (`run.py`'s `asyncio.gather`) across two independent tasks with two separate `ConnectionManager` instances, breaking the admin handoff broadcast entirely.

**`quick-commerce-frontend-service`**
- Family: `quick-commerce-frontend`, Desired tasks: 1, grace period 60s
- Networking: same 2 subnets, `quick-commerce-frontend-sg`
- Load balancing: single pass, `frontend:8501` → `quick-commerce-frontend-nlb` → listener `TCP:8501` → `frontend-tg`
- **Named `quick-commerce-frontend`** at creation (missing the `-service` suffix used everywhere else) — this mismatch against `ci_cd.yml`'s hardcoded `ECS_SERVICE_FRONTEND: quick-commerce-frontend-service` caused repeated `ServiceNotFoundException` failures until the workflow's env var was corrected to match the real service name instead of renaming the service.

---

## 11. API Gateway — evaluated, deliberately not built

Originally planned (HTTP API + VPC Link in front of the backend NLB, purely for request throttling/rate limiting). Reconsidered and dropped after weighing the setup complexity (VPC Link provisioning, route config, stage throttling) against the actual risk profile of a controlled-access deployment. `API_BASE_URL` points directly at the backend NLB (port 8000) instead. This can be added later as a pure infrastructure change if the deployment is ever shared at a scale where rate limiting becomes worth the complexity — no application code would need to change.

Similarly, **no ALB** (a single backend task has nothing to load-balance across) and **no CloudFront** (the app is session-driven/dynamic with little cacheable content) were built, for the same category of reason — each evaluated and consciously excluded, not overlooked.

---

## 12. CI/CD Pipeline (GitHub Actions)

`.github/workflows/ci_cd.yml`, two jobs:

**`build-and-push`**: builds both Docker images (with GitHub Actions cache via `docker/build-push-action`'s `type=gha` backend, added specifically to stop re-downloading `torch`/`whisper`/`docling` on every single run), tags each with both the commit SHA and `latest`, pushes both tags to ECR.

**`deploy`**: renders both task definitions from the 16 GitHub secrets via `sed`, registers new revisions with `aws ecs register-task-definition`, then updates both ECS services with `--force-new-deployment`.

**A real, root-cause bug lived here for a while**: the frontend's `update-service` command was missing an explicit `--task-definition` flag (the backend's had it, the frontend's didn't) — meaning `--force-new-deployment` alone only *restarts* the service on whatever revision it's already pinned to, not upgrade it to the newest registered one. This silently pinned the frontend service to revision 3 through 6+ subsequent pushes, each registering a new (correct) revision that the running service never actually picked up. Fixed by adding the missing flag to match the backend step's pattern.

---

## 13. What Actually Broke, In Order (for reference)

1. IAM service-linked role missing → cluster creation failed → fixed via `aws iam create-service-linked-role`
2. `CannotPullContainerError` → task def referenced `:latest`, workflow never pushed that tag → added `:latest` tag/push to the workflow
3. `CORS_ORIGINS` empty string → `JSONDecodeError` on startup → GitHub secret was unset
4. `CORS_ORIGINS` set but unquoted (`[http://...]` instead of `["http://..."]`) → same `JSONDecodeError`, different character offset → corrected the secret's exact format, later auto-mitigated in code via a `field_validator`
5. `API_BASE_URL` resolving to `*` in the running frontend → traced to `Profile.py`/`Cart_&_Checkout.py` calling `st.secrets.get(...)` directly instead of the shared `get_secret()` helper, which has no environment-variable fallback → fixed by routing both files through `get_secret()`
6. Frontend service stuck on an old task revision despite 9+ new registrations → missing `--task-definition` flag in the frontend deploy step → added the flag
7. Frontend service name mismatch (`quick-commerce-frontend` vs. workflow's expected `quick-commerce-frontend-service`) → `ServiceNotFoundException` → corrected the workflow's env var to match the real name
8. Backend service reached "Rollback failed" with 0 running tasks after several of the above compounded — resolved once the underlying `CORS_ORIGINS` and task-definition-targeting issues were fixed and a clean revision was explicitly forced via **Update service → Force new deployment**

---

## Final Live Configuration

| Value | Points to |
|---|---|
| `API_BASE_URL` | `http://quick-commerce-backend-nlb-0c1896f9be5fe529.elb.us-east-1.amazonaws.com:8000` |
| `WS_BASE_URL` | `ws://quick-commerce-backend-nlb-0c1896f9be5fe529.elb.us-east-1.amazonaws.com:8001` |
| `CORS_ORIGINS` | `["http://quick-commerce-frontend-nlb-a61d20f8a96f0f18.elb.us-east-1.amazonaws.com:8501"]` |
| Public app URL | `http://quick-commerce-frontend-nlb-a61d20f8a96f0f18.elb.us-east-1.amazonaws.com:8501` |
