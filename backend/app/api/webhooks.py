import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Request, BackgroundTasks, Form
from langchain_core.messages import HumanMessage

from backend.app.config import settings
from backend.app.graph.master_graph import get_compiled_graph_with_checkpointer
from backend.app.services.twilio_service import send_whatsapp_message
from backend.app.services.media_ingestion import upload_image_to_cloud, transcribe_audio, extract_pdf_from_twilio

logger = logging.getLogger(settings.APP_NAME)
router = APIRouter()

@router.post("/whatsapp")
async def twilio_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None),
):
    logger.info(f"Received WhatsApp message from {From}: {Body} (media: {NumMedia})")
    background_tasks.add_task(process_langgraph_agent, From, Body, NumMedia, MediaUrl0, MediaContentType0)
    return {"status": "processing"}

async def _ingest_media(media_url: str, content_type: str) -> dict:
    auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    if content_type.startswith("audio"):
        return {"transcript": await transcribe_audio(media_url, auth)}
    if content_type.startswith("image"):
        return {"photo_url": await upload_image_to_cloud(media_url, auth)}
    if content_type == "application/pdf":
        return {"pdf_text": await extract_pdf_from_twilio(media_url, auth)}
    return {}

def process_langgraph_agent(
    phone_number: str, message_body: str,
    num_media: int, media_url: Optional[str], content_type: Optional[str],
):
    try:
        effective_message = message_body

        if num_media and media_url:
            ingested = asyncio.run(_ingest_media(media_url, content_type or ""))
            if "transcript" in ingested:
                effective_message = f"{message_body} {ingested['transcript']}".strip()
            elif "photo_url" in ingested:
                effective_message = f"{message_body} [attached photo: {ingested['photo_url']}]".strip()
            elif "pdf_text" in ingested:
                effective_message = f"{message_body} [attached document: {ingested['pdf_text'][:1000]}]".strip()

        graph = get_compiled_graph_with_checkpointer()
        config = {"configurable": {"thread_id": phone_number}}
        input_state = {
            "messages": [HumanMessage(content=effective_message)],
            "user_profile": {"phone_number": phone_number},
            "thread_id": phone_number,
        }
        output_state = graph.invoke(input_state, config=config)
        final_message = output_state["messages"][-1].content
        logger.info(f"AI Response to {phone_number}: {final_message}")
        send_whatsapp_message(to_number=phone_number, body=final_message)

    except Exception as e:
        logger.error(f"Graph Execution Error for {phone_number}: {e}")
        send_whatsapp_message(to_number=phone_number, body="Sorry, something went wrong on my end. Please try again in a moment.")