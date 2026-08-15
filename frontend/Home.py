import streamlit as st
from frontend.components.chat_widget import render_chat_widget
from frontend.components.product_card import render_product_card
from frontend.services.api_client import get_backend_base_url
from frontend.utils.config import get_secret
import requests

st.set_page_config(
    page_title="AI Quick-Commerce",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

API_BASE_URL = get_secret("API_BASE_URL", "http://localhost:8000")
WS_BASE_URL = get_secret("WS_BASE_URL", "ws://localhost:8000")

st.session_state["API_BASE_URL"] = API_BASE_URL
st.session_state["WS_BASE_URL"] = WS_BASE_URL

if "cart" not in st.session_state:
    st.session_state.cart = []

st.title("🛒 AI-Powered Quick Commerce")
st.markdown("Welcome to the store! Browse manually, or just ask our AI to build a cart for you.")
st.divider()

col1, col2 = st.columns([7, 3])

with col1:
    st.subheader("🔥 Trending Products")

    try:
        resp = requests.get(f"{get_backend_base_url()}/products", params={"limit": 9})
        products = resp.json().get("products", []) if resp.status_code == 200 else []
    except requests.exceptions.ConnectionError:
        products = []

    if not products:
        st.info("Couldn't load products right now. Is the backend running?")
    else:
        grid_cols = st.columns(3)
        for index, product in enumerate(products):
            with grid_cols[index % 3]:
                render_product_card(product)

with col2:
    with st.container(border=True):
        render_chat_widget()