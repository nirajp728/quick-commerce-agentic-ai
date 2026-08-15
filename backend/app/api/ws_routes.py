import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from langchain_core.messages import AIMessage

from backend.app.config import settings
from backend.app.graph.master_graph import get_compiled_graph_with_checkpointer
from backend.app.services.ws_connection_manager import manager
from backend.app.services.twilio_service import send_whatsapp_message

logger = logging.getLogger(settings.APP_NAME)
router = APIRouter()

@router.websocket("/ws/admin")
async def admin_websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    if settings.ADMIN_WS_TOKEN and token != settings.ADMIN_WS_TOKEN:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"Message from Admin Dashboard: {data}")

            try:
                payload = json.loads(data)
                action = payload.get("action")

                if action == "subscribe":
                    manager.subscribe(websocket, payload.get("thread_ids", []))

                elif action == "resume" and "thread_id" in payload:
                    thread_id = payload["thread_id"]
                    logger.info(f"Admin resolving ticket. Resuming AI for {thread_id}...")
                    graph = get_compiled_graph_with_checkpointer()
                    config = {"configurable": {"thread_id": thread_id}}
                    graph.update_state(config, {"is_handed_off": False})
                    graph.invoke(None, config=config)
                    logger.info(f"Successfully resumed LangGraph AI for thread: {thread_id}")

                elif action == "admin_reply" and "thread_id" in payload and "message" in payload:
                    thread_id = payload["thread_id"]
                    reply_text = payload["message"]
                    graph = get_compiled_graph_with_checkpointer()
                    config = {"configurable": {"thread_id": thread_id}}
                    # Persist into the graph's own checkpointed history so
                    # the AI has full context if it resumes later.
                    graph.update_state(config, {"messages": [AIMessage(content=reply_text)]})
                    if thread_id.startswith("whatsapp:"):
                        send_whatsapp_message(to_number=thread_id, body=reply_text)
                    logger.info(f"Admin reply relayed to {thread_id}")

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Error handling admin WS message: {e}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)