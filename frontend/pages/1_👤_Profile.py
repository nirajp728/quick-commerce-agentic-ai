import streamlit as st
import requests
from frontend.utils.state_manager import init_session_state

st.set_page_config(page_title="My Profile", page_icon="👤")
init_session_state()

st.title("👤 User Profile & Wallet")
st.divider()

# NOTE: there's no real login/auth yet, so web sessions aren't tied to a
# Mongo user record. This demo shows the single seeded user's profile
# until real auth exists.
DEMO_PHONE = "whatsapp:+919876543210"
API_BASE_URL = st.secrets.get("API_BASE_URL", "http://localhost:8000")

@st.cache_data(ttl=30)
def fetch_profile(phone_number: str):
    resp = requests.get(f"{API_BASE_URL}/api/profile/{phone_number}")
    return resp.json() if resp.status_code == 200 else None

profile_data = fetch_profile(DEMO_PHONE)

if not profile_data:
    st.error("Couldn't load profile data. Is the backend running?")
    st.stop()

user, orders, refunds = profile_data["user"], profile_data["orders"], profile_data["refunds"]

st.metric("Wallet Balance", f"₹{user.get('wallet_balance', 0):.2f}")
st.caption(f"{user.get('name', '')} · {user.get('email', '')}")

st.subheader("📦 Order History")
if not orders:
    st.info("No orders yet — visit the store to place one.")
for order in orders:
    with st.expander(f"Order {order.get('order_id', '—')} — {order.get('status', 'Placed')}"):
        for item in order.get("items", []):
            st.markdown(f"- {item.get('qty', 1)}x {item.get('name')}")
        st.markdown(f"**Total: ₹{order.get('total', 0)}**")

st.subheader("💸 Refund History")
if not refunds:
    st.info("No refunds processed yet.")
for refund in refunds:
    st.markdown(f"- **{refund.get('item_name')}** — ₹{refund.get('amount')} (Order {refund.get('order_id')})")

st.divider()
st.info("Need a refund? Just ask the AI assistant on the Home page.")