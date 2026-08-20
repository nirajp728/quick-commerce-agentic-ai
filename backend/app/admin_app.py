import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.app.api.ws_routes import router as ws_router
from backend.app.services.ws_connection_manager import manager as ws_manager
from backend.app.config import settings
from backend.app.db.mongo_client import connect_to_mongo, close_mongo_connection

logger = logging.getLogger(settings.APP_NAME)

@asynccontextmanager
async def lifespan(app: FastAPI):
    connect_to_mongo()
    ws_manager.set_loop(asyncio.get_running_loop())
    yield
    close_mongo_connection()

admin_app = FastAPI(title=f"{settings.APP_NAME}-Admin", lifespan=lifespan)
admin_app.include_router(ws_router, tags=["WebSockets"])

@admin_app.get("/health", tags=["System"])
async def admin_health_check():
    return {"status": "online", "app": f"{settings.APP_NAME}-admin"}