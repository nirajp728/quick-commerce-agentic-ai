import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_health_check():
    """Validates that the FastAPI application is online and returns correct metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["app"] == "QuickCommerce-Agentic-AI"

def test_chat_endpoint_validation():
    """Ensures the /api/chat endpoint strictly enforces Pydantic request schemas."""
    # Sending an empty payload should trigger a 422 Unprocessable Entity validation error
    response = client.post("/api/chat", json={})
    assert response.status_code == 422

def test_whatsapp_webhook_missing_fields():
    """Ensures the Twilio webhook requires proper form fields."""
    response = client.post("/api/whatsapp", data={})
    assert response.status_code == 422