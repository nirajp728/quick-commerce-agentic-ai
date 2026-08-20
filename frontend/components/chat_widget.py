import base64
import uuid
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from frontend.services.api_client import send_chat_message, get_backend_base_url

def render_chat_widget():
    """
    Renders the chat UI. While a thread is handed off to a human admin,
    this polls the backend for admin replies and the moment the AI
    resumes — WhatsApp gets equivalent behavior for free via Twilio push,
    but the web channel has no push transport, so polling is the fix.
    """
    st.markdown("### 🤖 Quick-Commerce Assistant")
    st.caption("Ask for recipes, check your cart, or process a refund!")

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = f"web:{uuid.uuid4().hex[:8]}"

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi there! I can help you find products, plan meals, or process a refund. What do you need today?"}
        ]

    if "cart" not in st.session_state:
        st.session_state.cart = []

    if "is_handed_off" not in st.session_state:
        st.session_state.is_handed_off = False

    if "synced_message_count" not in st.session_state:
        st.session_state.synced_message_count = len(st.session_state.messages)

    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

    if st.session_state.is_handed_off:
        st_autorefresh(interval=4000, key="handoff_poll")
        _sync_from_backend()

    chat_container = st.container(height=500)

    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if st.session_state.is_handed_off:
        st.info("You're connected with a human support agent. The AI will resume once they're done.")

    uploaded_file = st.file_uploader(
        "Attach a photo, voice note, or PDF (optional)",
        type=["jpg", "jpeg", "png", "ogg", "mp3", "wav", "pdf"],
        disabled=st.session_state.is_handed_off,
        label_visibility="collapsed",
        key=f"file_uploader_{st.session_state.uploader_key}",
    )

    if uploaded_file is not None:
        st.caption(f"📎 Attached: {uploaded_file.name} — will be sent with your next message")

    if prompt := st.chat_input("Type your message here...", disabled=st.session_state.is_handed_off):
        file_data, file_content_type = None, None
        if uploaded_file is not None:
            file_bytes = uploaded_file.read()
            file_data = base64.b64encode(file_bytes).decode("utf-8")
            file_content_type = uploaded_file.type

        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)
                if uploaded_file is not None:
                    st.caption(f"📎 {uploaded_file.name}")

        with chat_container:
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    result = send_chat_message(
                        thread_id=st.session_state.thread_id,
                        message=prompt,
                        file_data=file_data,
                        file_content_type=file_content_type,
                    )
                    ai_response = result.get("response", "No response from AI.")
                    st.markdown(ai_response)

        st.session_state.messages.append({"role": "assistant", "content": ai_response})
        st.session_state.synced_message_count = len(st.session_state.messages)

        # Force the uploader to reset by changing its key, so the
        # attachment doesn't silently persist into future turns.
        if uploaded_file is not None:
            st.session_state.uploader_key += 1

        if "chat_cart" in result:
            st.session_state.cart = result["chat_cart"]

        if result.get("is_handed_off"):
            st.session_state.is_handed_off = True
            st.rerun()


def _sync_from_backend():
    try:
        resp = requests.get(
            f"{get_backend_base_url()}/thread_state/{st.session_state.thread_id}",
            timeout=5,
        )
        if resp.status_code != 200:
            return
        data = resp.json()
    except requests.exceptions.RequestException:
        return

    backend_messages = data.get("messages", [])
    if len(backend_messages) > st.session_state.synced_message_count:
        for m in backend_messages[st.session_state.synced_message_count:]:
            role = "user" if m["role"] == "human" else "assistant"
            st.session_state.messages.append({"role": role, "content": m["content"]})
        st.session_state.synced_message_count = len(backend_messages)

    if st.session_state.is_handed_off and not data.get("is_handed_off", True):
        st.session_state.is_handed_off = False
        st.session_state.messages.append({"role": "assistant", "content": "I'm back! How else can I help?"})