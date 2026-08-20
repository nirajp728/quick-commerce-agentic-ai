import base64
import logging
from langchain_core.messages import HumanMessage

from backend.app.graph.state import AgentState
from backend.app.services.media_ingestion import (
    describe_image_bytes, transcribe_audio_bytes, extract_pdf_text, upload_image_bytes_to_cloud,
)
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def ingestion_node(state: AgentState) -> dict:
    """Extracts text from any attached media and folds it into the current
    message before anything else in the graph sees it."""
    attachment_data = state.get("attachment_data")
    content_type = state.get("attachment_content_type")
    if not attachment_data or not content_type:
        return {}

    last_message = state["messages"][-1]
    raw_bytes = base64.b64decode(attachment_data)
    extra = ""

    if content_type.startswith("audio"):
        extra = f" {transcribe_audio_bytes(raw_bytes)}"
    elif content_type.startswith("image"):
        desc = describe_image_bytes(raw_bytes)
        url = upload_image_bytes_to_cloud(raw_bytes)
        extra = f" [image shows: {desc}] [attached photo: {url}]"
    elif content_type == "application/pdf":
        extra = f" [attached document: {extract_pdf_text(raw_bytes)[:1000]}]"

    if not extra:
        return {}

    updated = HumanMessage(content=last_message.content + extra)
    # Replace the just-added message with the enriched version.
    return {"messages": [updated], "attachment_data": None, "attachment_content_type": None}