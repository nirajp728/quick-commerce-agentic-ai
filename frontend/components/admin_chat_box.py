import streamlit as st

def render_admin_chat_box(thread_id: str):
    """
    NOTE: Not used by the current Admin Dashboard page — that page now
    handles live takeover directly via a real WebSocket connection
    (see frontend/services/ws_client.py). This component is kept only
    as a static placeholder; it does not send messages anywhere.
    """
    st.markdown(f"### Intervening on Thread: `{thread_id}`")
    st.info("Live reply-sending isn't wired up in this component. Use the Admin Dashboard page's takeover panel instead.")