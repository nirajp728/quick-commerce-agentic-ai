import base64
import logging
import requests

from frontend.utils.config import get_secret


def get_backend_base_url() -> str:
    base = get_secret("API_BASE_URL", "http://localhost:8000")
    return f"{base}/api"


def send_chat_message(thread_id: str, message: str, file_data: str = None, file_content_type: str = None) -> dict:
    """
    Sends the user's message to the FastAPI LangGraph backend.
    Returns the full response dict (response text, intent, sentiment,
    cart, handoff status) so callers can react to all of it.
    """
    payload = {"thread_id": thread_id, "message": message}
    if file_data and file_content_type:
        payload["file_data"] = file_data
        payload["file_content_type"] = file_content_type

    backend_url = get_backend_base_url()

    try:
        response = requests.post(f"{backend_url}/chat", json=payload)
        if response.status_code == 200:
            return response.json()
        logging.error(f"Backend Error: {response.status_code}")
        return {"response": "⚠️ Our AI is currently offline. Please try again later.", "chat_cart": [], "is_handed_off": False}
    except requests.exceptions.ConnectionError:
        return {"response": "⚠️ Could not connect to the backend server. Is FastAPI running?", "chat_cart": [], "is_handed_off": False}