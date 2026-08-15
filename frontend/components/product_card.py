import streamlit as st

def render_product_card(product: dict):
    """Renders an individual product with an Add to Cart button."""
    with st.container(border=True):
        st.markdown(f"## {product.get('icon', '📦')}")
        st.markdown(f"**{product.get('name', 'Product')}**")

        raw_price = product.get('price', 0)
        # Accept price as either a plain number (from Mongo) or a
        # pre-formatted "₹NNN" string (from static display data) without
        # crashing on either shape.
        if isinstance(raw_price, str):
            price_value = float(raw_price.replace("₹", "").strip() or 0)
        else:
            price_value = float(raw_price)

        st.markdown(f"*₹{price_value:g}*")

        button_key = f"btn_{product.get('product_id') or product.get('name', 'unknown')}"
        if st.button("Add to Cart", key=button_key, use_container_width=True):
            st.session_state.cart.append({
                "name": product.get("name"),
                "price": price_value,
                "qty": 1
            })
            st.toast(f"Added {product.get('name')} to cart!")