import base64
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from langchain_core.messages import HumanMessage

from backend.app.config import settings
from backend.app.graph.master_graph import get_compiled_graph_with_checkpointer

logger = logging.getLogger(settings.APP_NAME)
router = APIRouter()

DEMO_PHONE = "whatsapp:+919876543210"  # Single shared demo account (per earlier decision: no real auth/login)

class ChatRequest(BaseModel):
    thread_id: str
    message: str
    file_data: Optional[str] = None
    file_content_type: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    current_intent: str
    sentiment_score: float
    chat_cart: List[Dict[str, Any]] = []
    is_handed_off: bool = False

@router.post("/chat", response_model=ChatResponse)
async def process_web_chat(request: ChatRequest):
    """
    Synchronous endpoint for the Streamlit Web UI.
    Media (if any) is no longer pre-processed here — it's passed through
    as raw attachment_data/attachment_content_type and handled by the
    graph's own ingestion_node, so the extraction step is part of the
    graph's execution and checkpointed history like everything else.
    """
    logger.info(f"Web Chat Request from {request.thread_id}: {request.message}")

    try:
        graph = get_compiled_graph_with_checkpointer()
        config = {"configurable": {"thread_id": request.thread_id}}

        input_state = {
            "messages": [HumanMessage(content=request.message)],
            "user_profile": {"platform": "web_storefront", "phone_number": DEMO_PHONE},
            "thread_id": request.thread_id,
            "attachment_data": request.file_data,
            "attachment_content_type": request.file_content_type,
        }

        output_state = graph.invoke(input_state, config=config)

        return ChatResponse(
            response=output_state["messages"][-1].content,
            current_intent=output_state.get("current_intent", "unknown"),
            sentiment_score=output_state.get("sentiment_score", 0.0),
            chat_cart=output_state.get("chat_cart", []),
            is_handed_off=output_state.get("is_handed_off", False),
        )

    except Exception as e:
        logger.error(f"Web Chat Execution Error: {e}")
        raise HTTPException(status_code=500, detail="Internal AI Engine Error")