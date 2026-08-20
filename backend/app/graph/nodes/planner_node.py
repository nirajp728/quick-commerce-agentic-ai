import logging
from typing import List, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_structured_llm
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

REFUND_SLOT_FIELDS = ["refund_order_id", "refund_item_name", "refund_quantity", "refund_reason", "refund_photo_url"]

class DispatchTask(BaseModel):
    target: Literal["cart", "refund", "qa", "discovery"] = Field(
        description="'cart' to add/remove items in the shopping cart. 'refund' for refund/complaint requests "
                    "OR to continue an already-in-progress refund. 'qa' for store policy, order history, or "
                    "general knowledge questions. 'discovery' to check real-time product availability/price."
    )
    query: str = Field(description="A clean, self-contained instruction/query for that subgraph.")

class DispatchPlan(BaseModel):
    tasks: List[DispatchTask] = Field(description="One or more tasks needed to handle the user's CURRENT request. Can be multiple across different targets in the same turn.")

def _build_transcript(messages) -> str:
    return "\n".join(f"{'User' if m.type == 'human' else 'Assistant'}: {m.content}" for m in messages)

def _refund_progress_note(state: AgentState) -> str:
    if not state.get("refund_order_id"):
        return ""
    filled = [f for f in REFUND_SLOT_FIELDS if state.get(f)]
    missing = [f for f in REFUND_SLOT_FIELDS if not state.get(f)]
    if not missing:
        return ""
    return (f"\n\nNOTE: A refund is already in progress (order {state.get('refund_order_id')}). "
            f"Filled: {filled}. Still missing: {missing}.\n"
            f"MANDATORY: dispatch a 'refund' task with the user's message as the query, ALWAYS, whenever "
            f"a refund is in progress — refund's own logic will extract whatever slot info is present and "
            f"re-ask if still incomplete, so there is no downside to always including it.\n"
            f"ADDITIONALLY, if the user's message asks ANYTHING that requires looking up real data you "
            f"don't already have — what items were in the order, order status, order date, or any other "
            f"factual question about this order — you MUST ALSO dispatch a 'qa' task in the SAME turn with "
            f"a query asking about that order's contents. Do not rely on the refund subgraph to answer "
            f"factual questions about the order; it cannot look anything up. When in doubt about whether "
            f"a question needs a lookup, dispatch 'qa' anyway — there is no cost to an extra qa task that "
            f"turns out unnecessary, but a missing one leaves the user's question unanswered.")

def planner_node(state: AgentState) -> dict:
    logger.info("Executing Planner Node...")
    transcript = _build_transcript(state.get("messages", []))
    refund_note = _refund_progress_note(state)

    system_prompt = """You are a planning agent for a quick-commerce assistant.
    Four subgraphs are available:
    - cart: adds or removes items in the user's shopping cart.
    - refund: handles refund/complaint requests for a past order (slot-filling: order id, item, qty, reason, photo).
    - qa: answers store policy questions, the user's own order history, or general-knowledge questions
      (uses the store's vector database first, and falls back to a live web search if that's insufficient).
    - discovery: checks the live product catalog for what's currently in stock and at what price.
      Discovery does NOT know facts about the world (recipes, dish ingredients, general knowledge) —
      it can only tell you whether a specific item is available in the store.

    Read the full conversation and decide which subgraph(s) are needed to fully handle the user's
    CURRENT request. A single request can need more than one — e.g. "what are burger ingredients and
    do you have them, add what's available" needs both a qa/discovery-style check AND a cart task.
    """ + refund_note

    plan: DispatchPlan = (
        ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Conversation so far:\n{transcript}")
        ]) | get_structured_llm(DispatchPlan)
    ).invoke({"transcript": transcript})

    logger.info(f"Planner dispatching: {[(t.target, t.query) for t in plan.tasks]}")
    return {"dispatch_tasks": [t.model_dump() for t in plan.tasks]}