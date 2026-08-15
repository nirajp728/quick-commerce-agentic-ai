import uuid
import streamlit as st

def init_session_state():
    """Initializes global Streamlit variables used across all multi-page apps."""
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = f"web:{uuid.uuid4().hex[:8]}"
        
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Welcome! How can I help you today?"}]
        
    if "cart" not in st.session_state:
        st.session_state.cart = []
        
    if "wallet_balance" not in st.session_state:
        st.session_state.wallet_balance = 500.00