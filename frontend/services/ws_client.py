import json
import queue
import threading
import websocket  # pip package: websocket-client


def start_admin_listener(ws_url: str, message_queue: queue.Queue) -> websocket.WebSocketApp:
    """
    Connects to the backend's /ws/admin endpoint in a background thread.
    Incoming JSON messages (handoff alerts) are pushed onto message_queue
    for the Streamlit main thread to drain on each rerun. Returns the
    WebSocketApp instance so the caller can also .send() resume commands.
    """
    def on_message(ws, message):
        try:
            message_queue.put(json.loads(message))
        except json.JSONDecodeError:
            pass

    def on_error(ws, error):
        message_queue.put({"event": "connection_error", "detail": str(error)})

    def on_close(ws, close_status_code, close_msg):
        message_queue.put({"event": "connection_closed"})

    ws_app = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    thread = threading.Thread(target=ws_app.run_forever, daemon=True)
    thread.start()

    return ws_app