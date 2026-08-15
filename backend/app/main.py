import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.webhooks import router as webhooks_router
from backend.app.api.ws_routes import router as ws_router
from backend.app.api.chat_routes import router as chat_router
from backend.app.api.products_routes import router as products_router
from backend.app.api.profile_routes import router as profile_router
from backend.app.api.checkout_routes import router as checkout_router
from backend.app.services.ws_connection_manager import manager as ws_manager
from backend.app.config import settings
from backend.app.db.mongo_client import connect_to_mongo, close_mongo_connection

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(settings.APP_NAME)

@asynccontextmanager
async def lifespan(app: FastAPI):
    connect_to_mongo()
    ws_manager.set_loop(asyncio.get_running_loop())
    yield
    close_mongo_connection()

app = FastAPI(
    title=settings.APP_NAME,
    description="Omnichannel Agentic AI Platform for Quick Commerce",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(webhooks_router, prefix="/api", tags=["Webhooks"])
app.include_router(chat_router, prefix="/api", tags=["Web Chat"])
app.include_router(products_router, prefix="/api", tags=["Products"])
app.include_router(profile_router, prefix="/api", tags=["Profile"])
app.include_router(checkout_router, prefix="/api", tags=["Checkout"])
app.include_router(ws_router, tags=["WebSockets"])

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "online", "app": settings.APP_NAME, "environment": settings.ENVIRONMENT}