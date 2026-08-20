import logging
import tempfile
import httpx
import cloudinary
import cloudinary.uploader
import whisper
from docling.document_converter import DocumentConverter
from langchain_core.messages import HumanMessage
from backend.app.config import settings
from backend.app.utils.llm_factory import get_llm
import base64

logger = logging.getLogger(settings.APP_NAME)

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)

_whisper_model = None
_docling_converter = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        logger.info("Loading Whisper model (base)...")
        _whisper_model = whisper.load_model("base")
    return _whisper_model

def _get_docling_converter():
    global _docling_converter
    if _docling_converter is None:
        _docling_converter = DocumentConverter()
    return _docling_converter

def upload_image_bytes_to_cloud(image_bytes: bytes) -> str:
    result = cloudinary.uploader.upload(image_bytes, folder="quick_commerce_refunds")
    return result["secure_url"]

def describe_image_bytes(image_bytes: bytes) -> str:
    """
    Vision description: what the reviewer/router/planner actually needs to
    reason about an image's content. Uploading to Cloudinary only produces
    a URL — this is what turns image data into understandable text, the
    same role Whisper plays for audio and Docling plays for PDFs.
    """
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    message = HumanMessage(content=[
        {"type": "text", "text": "Describe what is shown in this image factually and concisely, "
                                   "in 1-3 sentences. If it appears to show a damaged, expired, or "
                                   "defective product, note that specifically."},
        {"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64_image}"},
    ])
    response = get_llm().invoke([message]).content
    if isinstance(response, list):
        response = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in response)
    return response.strip()

def transcribe_audio_bytes(audio_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".ogg") as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        result = _get_whisper_model().transcribe(tmp.name)
    return result["text"].strip()

def extract_pdf_text(pdf_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        doc = _get_docling_converter().convert(tmp.name).document
    return doc.export_to_markdown().strip()

async def _download_from_twilio(media_url: str, auth: tuple) -> bytes:
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url, auth=auth)
        resp.raise_for_status()
        return resp.content

async def upload_image_to_cloud(media_url: str, auth: tuple) -> str:
    return upload_image_bytes_to_cloud(await _download_from_twilio(media_url, auth))

async def describe_image(media_url: str, auth: tuple) -> str:
    return describe_image_bytes(await _download_from_twilio(media_url, auth))

async def transcribe_audio(media_url: str, auth: tuple) -> str:
    return transcribe_audio_bytes(await _download_from_twilio(media_url, auth))

async def extract_pdf_from_twilio(media_url: str, auth: tuple) -> str:
    return extract_pdf_text(await _download_from_twilio(media_url, auth))