import streamlit as st

def render_cart_sidebar():
    """
    Renders a persistent sidebar showing the current items in the user's cart.
    This reflects the state mutated by the AI's `cart_graph`.
    """
    st.sidebar.title("🛒 Your Cart")
    st.sidebar.divider()
    
    # Initialize a mock cart in session state if it doesn't exist
    if "cart" not in st.session_state:
        st.session_state.cart = []
        
    if not st.session_state.cart:
        st.sidebar.info("Your cart is empty. Ask the AI to add some items!")
        return

    # Calculate Subtotal
    total = 0
    for item in st.session_state.cart:
        price = item.get("price", 0)
        qty = item.get("qty", 1)
        subtotal = price * qty
        total += subtotal
        
        st.sidebar.markdown(f"**{qty}x {item['name']}**")
        st.sidebar.caption(f"₹{price} each | Subtotal: ₹{subtotal}")
        
    st.sidebar.divider()
    st.sidebar.subheader(f"Total: ₹{total}")
    
    # Navigation to Checkout
    if st.sidebar.button("🛍️ Proceed to Checkout", use_container_width=True):
        st.switch_page("pages/2_🛍️_Cart_&_Checkout.py")