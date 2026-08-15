import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from langchain_core.messages import HumanMessage

from backend.app.config import settings
from backend.app.graph.master_graph import get_compiled_graph_with_checkpointer
from backend.app.services.media_ingestion import upload_image_bytes_to_cloud, transcribe_audio_bytes, extract_pdf_text
import base64

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

def _ingest_web_file(file_data: str, content_type: str) -> str:
    """Returns text to append to the user's message describing the upload."""
    raw_bytes = base64.b64decode(file_data)
    if content_type.startswith("audio"):
        return f" {transcribe_audio_bytes(raw_bytes)}"
    if content_type.startswith("image"):
        return f" [attached photo: {upload_image_bytes_to_cloud(raw_bytes)}]"
    if content_type == "application/pdf":
        return f" [attached document: {extract_pdf_text(raw_bytes)[:1000]}]"
    return ""

@router.post("/chat", response_model=ChatResponse)
async def process_web_chat(request: ChatRequest):
    """
    Synchronous endpoint for the Streamlit Web UI.
    Invokes the LangGraph engine and awaits the final response.
    """
    logger.info(f"Web Chat Request from {request.thread_id}: {request.message}")

    try:
        effective_message = request.message
        if request.file_data and request.file_content_type:
            effective_message += _ingest_web_file(request.file_data, request.file_content_type)

        graph = get_compiled_graph_with_checkpointer()
        config = {"configurable": {"thread_id": request.thread_id}}

        input_state = {
            "messages": [HumanMessage(content=effective_message)],
            "user_profile": {"platform": "web_storefront", "phone_number": DEMO_PHONE},
            "thread_id": request.thread_id,
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