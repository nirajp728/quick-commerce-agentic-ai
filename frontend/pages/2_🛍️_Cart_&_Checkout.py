import streamlit as st
import requests
from frontend.utils.config import get_secret

st.set_page_config(page_title="Checkout | Quick-Commerce", page_icon="🛍️", layout="centered")



API_BASE_URL = get_secret("API_BASE_URL", "http://localhost:8000")
DEMO_PHONE = "whatsapp:+919876543210"  # see note in Profile.py

st.title("🛍️ Secure Checkout")
st.markdown("Review your items and pay using your Wallet Balance.")
st.divider()

if "cart" not in st.session_state:
    st.session_state.cart = []
if "payment_success" not in st.session_state:
    st.session_state.payment_success = False
if "last_order_id" not in st.session_state:
    st.session_state.last_order_id = None

if st.session_state.payment_success:
    st.balloons()
    st.success(f"Payment successful! Order `{st.session_state.last_order_id}` is being packed.")
    if st.button("Track Order"):
        st.session_state.payment_success = False
        st.switch_page("pages/1_👤_Profile.py")
    st.stop()

if not st.session_state.cart:
    st.warning("Your cart is empty!")
    if st.button("← Back to Store"):
        st.switch_page("Home.py")
    st.stop()

st.subheader("Order Summary")
total_amount = 0
for item in st.session_state.cart:
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1: st.write(f"**{item['name']}**")
    with col2: st.write(f"Qty: {item.get('qty', 1)}")
    with col3:
        item_total = item.get('price', 0) * item.get('qty', 1)
        st.write(f"**₹{item_total}**")
        total_amount += item_total

st.divider()

try:
    profile_resp = requests.get(f"{API_BASE_URL}/api/profile/{DEMO_PHONE}")
    wallet_balance = profile_resp.json()["user"]["wallet_balance"] if profile_resp.status_code == 200 else 0
except requests.exceptions.ConnectionError:
    st.error("Could not reach the backend to check wallet balance.")
    st.stop()

col_total, col_wallet = st.columns(2)
col_total.metric("Amount to Pay", f"₹{total_amount}")
col_wallet.metric("Wallet Balance", f"₹{wallet_balance}")

if wallet_balance < total_amount:
    st.error("Insufficient wallet balance. Please remove items or top up your wallet.")
else:
    st.success("✅ Sufficient balance available.")
    if st.button("💳 Confirm & Pay", type="primary", use_container_width=True):
        with st.spinner("Processing payment..."):
            resp = requests.post(f"{API_BASE_URL}/api/checkout", json={"phone_number": DEMO_PHONE, "items": st.session_state.cart})
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.cart = []
            st.session_state.payment_success = True
            st.session_state.last_order_id = data["order_id"]
            st.rerun()
        else:
            st.error(f"Checkout failed: {resp.json().get('detail', 'Unknown error')}")