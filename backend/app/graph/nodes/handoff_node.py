import logging
from langchain_core.messages import AIMessage
from backend.app.graph.state import AgentState
from backend.app.services.ws_connection_manager import manager as ws_manager
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def handoff_node(state: AgentState) -> dict:
    logger.info("Executing Handoff Node: Escalating to Human Agent.")

    thread_id = state.get("thread_id", "unknown")
    last_user_message = state["messages"][-1].content if state.get("messages") else ""

    ws_manager.broadcast_threadsafe({
        "event": "handoff",
        "thread_id": thread_id,
        "sentiment_score": state.get("sentiment_score", 0.0),
        "last_message": last_user_message,
    })

    return {
        "is_handed_off": True,
        "messages": [AIMessage(content="I understand your concern. I am pausing my AI operations and transferring this chat to a human support agent. They will be with you shortly.")]
    }