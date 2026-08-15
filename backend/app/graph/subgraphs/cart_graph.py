import json
import logging
from typing import List, Literal
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
    quantity: int = Field(default=1, description="How many units. Default to 1 if not stated.")
    action: Literal["add", "remove"] = Field(description="Whether the user wants to add this item to the cart or remove it.")

class CartExtraction(BaseModel):
    items: List[CartItemRequest] = Field(description="Every distinct product the user mentioned, each tagged as add or remove.")

def cart_manager_node(state: AgentState) -> dict:
    """
    Extracts every cart item + quantity + action (add/remove) mentioned in
    the message, and mutates chat_cart accordingly.
    """
    logger.info("Executing Cart Subgraph: cart_manager_node")
    last_message = state["messages"][-1].content
    current_cart = state.get("chat_cart", [])
    offered_items = state.get("last_offered_items", [])

    if offered_items:
        # Ask the LLM directly whether this message means "add what was just
        # shown to me" — covers any phrasing, not just a fixed set of exact
        # strings like "add this"/"add that".
        class ReferentialAddCheck(BaseModel):
            wants_previously_offered: bool = Field(
                description="True if the user is asking to add the items that were just shown/offered to them, in any phrasing."
            )
        ref_check: ReferentialAddCheck = (
            ChatPromptTemplate.from_messages([
                ("system", "The assistant just showed the user a list of available products: {items}. "
                           "Does the user's message mean 'add those items to my cart'?"),
                ("human", "{input}")
            ]) | get_structured_llm(ReferentialAddCheck)
        ).invoke({"items": ", ".join(i["name"] for i in offered_items), "input": last_message})

        if ref_check.wants_previously_offered:
            for item in offered_items:
                current_cart.append({
                    "product_id": item["product_id"],
                    "name": item["name"],
                    "qty": 1,
                    "price": item["price"]
                })
            added_lines = [f"**{i['name']}** x1 (₹{i['price']} each)" for i in offered_items]
            return {
                "chat_cart": current_cart,
                "last_offered_items": [],
                "messages": [AIMessage(content="Added to your cart:\n- " + "\n- ".join(added_lines))]
            }

    llm = get_structured_llm(CartExtraction)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a smart shopping cart assistant.
        Extract every distinct product the user mentions, its quantity (default 1 if unstated),
        and whether they want to ADD it to their cart or REMOVE it from their cart.
        "remove 2 lays" -> action=remove, quantity=2, query=lays.
        "add 3 chicken" -> action=add, quantity=3, query=chicken."""),
        ("human", "{input}")
    ])

    chain = prompt | llm
    extraction: CartExtraction = chain.invoke({"input": last_message})

    if not extraction.items:
        return {"messages": [AIMessage(content="I couldn't tell what you'd like to add or remove — could you name the item?")]}

    added_lines = []
    removed_lines = []
    not_found_alternatives = []
    not_in_cart = []

    for requested in extraction.items:
        if requested.action == "remove":
            matching = [c for c in current_cart if requested.query.lower() in c["name"].lower()]
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

        tool_result = json.loads(check_inventory.invoke({"query": requested.query, "limit": 1}))
        if tool_result.get("status") == "success" and tool_result.get("items"):
            best_match = tool_result["items"][0]
            current_cart.append({
                "product_id": best_match["product_id"],
                "name": best_match["name"],
                "qty": requested.quantity,
                "price": best_match["price"]
            })
            added_lines.append(f"**{best_match['name']}** x{requested.quantity} (₹{best_match['price']} each)")
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
        "messages": [AIMessage(content="\n\n".join(parts))]
    }

# Compile the Subgraph
builder = StateGraph(AgentState)
builder.add_node("cart_manager", cart_manager_node)
builder.add_edge(START, "cart_manager")
builder.add_edge("cart_manager", END)

cart_subgraph = builder.compile()