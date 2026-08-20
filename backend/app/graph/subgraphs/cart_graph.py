import json
import logging
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_structured_llm
from backend.app.tools.db_tools import check_inventory
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

class CartItemRequest(BaseModel):
    query: str = Field(description="The product name or search term, e.g. 'milk', 'chicken breast'.")
    quantity: Optional[int] = Field(default=None, description="How many units, ONLY if explicitly stated by the user. Leave unset if not mentioned.")
    action: Literal["add", "remove"] = Field(description="Whether the user wants to add this item to the cart or remove it.")

class CartExtraction(BaseModel):
    items: List[CartItemRequest] = Field(description="Every distinct product the user mentioned, each tagged as add or remove.")

class ReferentialAddCheck(BaseModel):
    wants_previously_offered: bool = Field(
        description="True if the user is asking to add the items that were just shown/offered to them, in any phrasing."
    )

class CartViewCheck(BaseModel):
    wants_to_view_cart: bool = Field(
        description="True if the user is asking to see/check what's currently in their cart, not add or remove anything."
    )

class CartClearCheck(BaseModel):
    wants_to_clear_cart: bool = Field(
        description="True if the user wants to remove ALL/everything from their cart, not specific named items."
    )

def _add_to_cart(current_cart: list, product_id: str, name: str, qty: int, price: float) -> None:
    """Merges into an existing line for the same product instead of
    appending a duplicate entry."""
    for item in current_cart:
        if item["product_id"] == product_id:
            item["qty"] += qty
            return
    current_cart.append({"product_id": product_id, "name": name, "qty": qty, "price": price})

def cart_manager_node(state: AgentState) -> dict:
    """
    Extracts every cart item + quantity + action (add/remove) mentioned in
    the message, and mutates chat_cart accordingly. Handles pure "view my
    cart" and "clear my cart" requests as special cases. For 'add', an
    unstated quantity defaults to 1. For 'remove', an unstated quantity
    asks the user to clarify how many, rather than silently assuming 1 —
    "remove amul" most naturally means "remove all of it," not "remove
    exactly one unit," so guessing would likely be wrong.
    """
    logger.info("Executing Cart Subgraph: cart_manager_node")
    last_message = state["messages"][-1].content
    current_cart = state.get("chat_cart", [])
    offered_items = state.get("last_offered_items", [])

    view_check: CartViewCheck = (
        ChatPromptTemplate.from_messages([
            ("system", "Does this message ask to view/check the current cart contents, rather than "
                       "add or remove items?"),
            ("human", "{input}")
        ]) | get_structured_llm(CartViewCheck)
    ).invoke({"input": last_message})

    if view_check.wants_to_view_cart:
        logger.info("Cart Subgraph: view-cart request detected.")
        if not current_cart:
            return {"messages": [AIMessage(content="Your cart is currently empty.")]}
        lines = [f"- **{item['name']}** x{item['qty']} (₹{item['price']} each)" for item in current_cart]
        total = sum(item['price'] * item['qty'] for item in current_cart)
        return {"messages": [AIMessage(content="Your current cart:\n" + "\n".join(lines) + f"\n\n**Total: ₹{total}**")]}

    clear_check: CartClearCheck = (
        ChatPromptTemplate.from_messages([
            ("system", "Does this message ask to remove ALL items / clear the entire cart, rather than "
                       "specific named items?"),
            ("human", "{input}")
        ]) | get_structured_llm(CartClearCheck)
    ).invoke({"input": last_message})

    if clear_check.wants_to_clear_cart:
        logger.info("Cart Subgraph: clear-cart request detected.")
        return {"chat_cart": [], "messages": [AIMessage(content="Your cart has been cleared.")]}

    logger.info(f"Referential check gate: offered_items={offered_items}, last_message={last_message!r}")

    if offered_items:
        ref_check: ReferentialAddCheck = (
            ChatPromptTemplate.from_messages([
                ("system", "The assistant just showed the user a list of available products: {items}. "
                           "Does the user's message mean 'add those items to my cart'? Only say True if "
                           "they are clearly referring back to that offer (e.g. 'add this', 'add those', "
                           "'yes add them') — not for an unrelated new request naming a different product."),
                ("human", "{input}")
            ]) | get_structured_llm(ReferentialAddCheck)
        ).invoke({"items": ", ".join(i["name"] for i in offered_items), "input": last_message})

        logger.info(f"Referential check result: wants_previously_offered={ref_check.wants_previously_offered}")

        if ref_check.wants_previously_offered:
            for item in offered_items:
                _add_to_cart(current_cart, item["product_id"], item["name"], 1, item["price"])
            added_lines = [f"**{i['name']}** x1 (₹{i['price']} each)" for i in offered_items]
            return {
                "chat_cart": current_cart,
                "last_offered_items": [],
                "messages": [AIMessage(content="Added to your cart:\n- " + "\n- ".join(added_lines))]
            }
        offered_items = []

    llm = get_structured_llm(CartExtraction)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a smart shopping cart assistant.
        Extract every distinct product the user mentions, and whether they want to ADD it to their
        cart or REMOVE it. Only set quantity if the user explicitly states a number — leave it unset
        otherwise (e.g. "add butter" -> quantity unset; "add 3 chicken" -> quantity=3).
        "remove 2 lays" -> action=remove, quantity=2, query=lays.
        "remove butter" -> action=remove, quantity unset, query=butter."""),
        ("human", "{input}")
    ])

    chain = prompt | llm
    extraction: CartExtraction = chain.invoke({"input": last_message})
    logger.info(f"CartExtraction raw output: {extraction.model_dump()}")

    if not extraction.items:
        return {"messages": [AIMessage(content="I couldn't tell what you'd like to add or remove — could you name the item?")],
                "last_offered_items": offered_items}

    added_lines = []
    removed_lines = []
    not_found_alternatives = []
    not_in_cart = []

    for requested in extraction.items:
        if requested.action == "remove":
            matching = [c for c in current_cart if requested.query.lower() in c["name"].lower()]

            if requested.quantity is None:
                if not matching:
                    not_in_cart.append(requested.query)
                    continue
                total_qty = sum(c["qty"] for c in matching)
                return {
                    "chat_cart": current_cart,
                    "last_offered_items": offered_items,
                    "messages": [AIMessage(content=f"You have {total_qty}x {matching[0]['name']} in your cart. How many would you like to remove?")]
                }

            if not matching:
                not_in_cart.append(requested.query)
                continue

            to_remove = requested.quantity
            for cart_item in matching:
                if to_remove <= 0:
                    break
                if cart_item["qty"] <= to_remove:
                    to_remove -= cart_item["qty"]
                    current_cart.remove(cart_item)
                    removed_lines.append(f"**{cart_item['name']}** x{cart_item['qty']}")
                else:
                    cart_item["qty"] -= to_remove
                    removed_lines.append(f"**{cart_item['name']}** x{to_remove}")
                    to_remove = 0
            continue

        add_qty = requested.quantity or 1
        tool_result_str = check_inventory.invoke({"query": requested.query, "limit": 1})
        logger.info(f"check_inventory result for '{requested.query}': {tool_result_str}")
        tool_result = json.loads(tool_result_str)
        if tool_result.get("status") == "success" and tool_result.get("items"):
            best_match = tool_result["items"][0]
            _add_to_cart(current_cart, best_match["product_id"], best_match["name"], add_qty, best_match["price"])
            added_lines.append(f"**{best_match['name']}** x{add_qty} (₹{best_match['price']} each)")
        else:
            alt_result = json.loads(check_inventory.invoke({"query": requested.query, "limit": 3}))
            not_found_alternatives.append((requested.query, alt_result))

    parts = []
    if added_lines:
        parts.append("Added to your cart:\n- " + "\n- ".join(added_lines))
    if removed_lines:
        parts.append("Removed from your cart:\n- " + "\n- ".join(removed_lines))
    if not_in_cart:
        parts.append(f"Couldn't find {', '.join(not_in_cart)} in your cart to remove.")

    for query, alt_result in not_found_alternatives:
        if alt_result.get("status") == "success" and alt_result.get("items"):
            alt_lines = [f"{i['name']} (₹{i['price']})" for i in alt_result["items"]]
            parts.append(f"Couldn't find \"{query}\", but these are in stock: {', '.join(alt_lines)}. Want me to add one?")
        else:
            parts.append(f"Couldn't find \"{query}\" or anything similar in stock right now.")

    return {
        "chat_cart": current_cart,
        "last_offered_items": offered_items,
        "messages": [AIMessage(content="\n\n".join(parts))]
    }

# Compile the Subgraph
builder = StateGraph(AgentState)
builder.add_node("cart_manager", cart_manager_node)
builder.add_edge(START, "cart_manager")
builder.add_edge("cart_manager", END)

cart_subgraph = builder.compile()