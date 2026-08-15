import asyncio
import logging
from typing import Dict, Set, Optional
from fastapi import WebSocket

from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

class ConnectionManager:
    """Manages active WebSocket connections for the Admin Dashboard.
    Lives in its own module (not ws_routes.py) so nodes like handoff_node
    can import it without creating a circular import with master_graph."""
    def __init__(self):
        self.active_connections: Dict[WebSocket, Set[str]] = {}  # empty set = receives everything
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.main_loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = set()
        logger.info(f"Admin connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)
        logger.info(f"Admin disconnected. Active connections: {len(self.active_connections)}")

    def subscribe(self, websocket: WebSocket, thread_ids: list):
        self.active_connections[websocket] = set(thread_ids)

    async def broadcast(self, message: dict):
        thread_id = message.get("thread_id")
        for connection, subscribed in list(self.active_connections.items()):
            if subscribed and thread_id and thread_id not in subscribed:
                continue  # this admin only wants specific tickets, and this isn't one of them
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {e}")

    def broadcast_threadsafe(self, message: dict):
        if not self.main_loop:
            logger.warning("Cannot broadcast: main event loop not set yet.")
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self.main_loop)

manager = ConnectionManager()