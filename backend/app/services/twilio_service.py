import logging
from twilio.rest import Client
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def send_whatsapp_message(to_number: str, body: str):
    """Pushes an asynchronous outbound message to a WhatsApp user."""
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning(f"Twilio credentials missing. Simulating WhatsApp send to {to_number}: {body}")
        return

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            body=body,
            to=to_number
        )
        logger.info(f"WhatsApp message sent successfully: {message.sid}")
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")