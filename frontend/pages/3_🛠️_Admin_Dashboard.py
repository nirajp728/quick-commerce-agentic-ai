import json
import queue
import requests
import streamlit as st
from frontend.services.ws_client import start_admin_listener
from frontend.services.api_client import get_backend_base_url
from frontend.utils.config import get_secret

st.set_page_config(page_title="Admin | Live Support", page_icon="🛠️", layout="wide")

_ws_token = get_secret("ADMIN_WS_TOKEN", "")
WS_URL = get_secret("WS_BASE_URL", "ws://localhost:8000") + f"/ws/admin?token={_ws_token}"

st.title("🛠️ Admin Command Center")
st.markdown("Monitor live customer sentiment and take over chats from the AI.")
st.divider()

# ------------------------------------------------------------------
# 1. Real WebSocket connection (background thread) + inbound queue
# ------------------------------------------------------------------
if "admin_ws_queue" not in st.session_state:
    st.session_state.admin_ws_queue = queue.Queue()

if "admin_ws_app" not in st.session_state:
    st.session_state.admin_ws_app = start_admin_listener(WS_URL, st.session_state.admin_ws_queue)

if "active_tickets" not in st.session_state:
    st.session_state.active_tickets = []

if "ws_connected" not in st.session_state:
    st.session_state.ws_connected = True

# On first load, backfill any handoffs that happened before this admin
# dashboard connected — live broadcast alone can't reach a tab that wasn't
# open yet.
if "backfilled_handoffs" not in st.session_state:
    try:
        resp = requests.get(f"{get_backend_base_url()}/active_handoffs", timeout=5)
        if resp.status_code == 200:
            for ticket in resp.json().get("active_handoffs", []):
                already_queued = any(t["thread_id"] == ticket["thread_id"] for t in st.session_state.active_tickets)
                if not already_queued:
                    st.session_state.active_tickets.append(ticket)
    except requests.exceptions.RequestException:
        pass
    st.session_state.backfilled_handoffs = True

# Drain anything that's arrived since the last rerun
while not st.session_state.admin_ws_queue.empty():
    payload = st.session_state.admin_ws_queue.get()
    event = payload.get("event")

    if event == "handoff":
        thread_id = payload.get("thread_id", "unknown")
        already_queued = any(t["thread_id"] == thread_id for t in st.session_state.active_tickets)
        if not already_queued:
            st.session_state.active_tickets.append({
                "thread_id": thread_id,
                "issue": payload.get("last_message", "(no message)"),
                "sentiment": payload.get("sentiment_score", 0.0),
            })
    elif event in ("connection_error", "connection_closed"):
        st.session_state.ws_connected = False

# ------------------------------------------------------------------
# 2. Top-Level Metrics
# ------------------------------------------------------------------
col1, col2, col3 = st.columns(3)
col1.metric("Active Escalations", len(st.session_state.active_tickets), delta_color="inverse")
col2.metric("AI Resolution Rate", "94%", "2%")
col3.metric("Avg Sentiment Score", "+0.6", "-0.1")

st.divider()

st.sidebar.subheader("📡 Connection Status")
if st.session_state.ws_connected:
    st.sidebar.success(f"Connected to: {WS_URL.split('?')[0]}")
else:
    st.sidebar.error(f"Disconnected from: {WS_URL.split('?')[0]}")
if st.sidebar.button("🔄 Refresh"):
    st.session_state.backfilled_handoffs = False
    st.rerun()

# ------------------------------------------------------------------
# 3. Escalation Queue & Takeover Interface
# ------------------------------------------------------------------
col_queue, col_chat = st.columns([1, 2])

with col_queue:
    st.subheader("🚨 Escalation Queue")

    if not st.session_state.active_tickets:
        st.info("No active escalations. The AI is handling everything!")
    else:
        for index, ticket in enumerate(st.session_state.active_tickets):
            with st.container(border=True):
                st.markdown(f"**Thread:** `{ticket['thread_id']}`")
                st.markdown(f"**Issue:** {ticket['issue']}")
                st.markdown(f"**Sentiment Score:** 🔴 `{ticket['sentiment']}`")

                if st.button("Takeover Chat", key=f"takeover_{index}"):
                    st.session_state.current_takeover = ticket['thread_id']

with col_chat:
    st.subheader("💬 Live Intervention Panel")

    if "current_takeover" in st.session_state:
        st.warning(f"You have taken over thread: **{st.session_state.current_takeover}**")
        st.markdown("*The AI is paused. Type below to relay a message directly to the customer.*")

        reply = st.chat_input("Type your response to the customer...")
        if reply:
            st.session_state.admin_ws_app.send(json.dumps({
                "action": "admin_reply",
                "thread_id": st.session_state.current_takeover,
                "message": reply,
            }))
            st.success("Message relayed to the customer.")

        if st.button("Resolve & Resume AI"):
            st.session_state.admin_ws_app.send(json.dumps({
                "action": "resume",
                "thread_id": st.session_state.current_takeover,
            }))
            st.session_state.active_tickets = [
                t for t in st.session_state.active_tickets
                if t["thread_id"] != st.session_state.current_takeover
            ]
            del st.session_state["current_takeover"]
            st.success("Resume command sent. AI will pick back up.")
            st.rerun()
    else:
        st.info("Select a ticket from the queue to intervene.")