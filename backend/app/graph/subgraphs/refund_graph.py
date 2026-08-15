import json
import logging
import re
from typing import Optional
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_structured_llm
from backend.app.tools.db_tools import process_refund_credit, check_inventory, check_existing_refund
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

# ------------------------------------------------------------------
# 1. Pydantic Schema for Slot Extraction
# ------------------------------------------------------------------
class RefundExtraction(BaseModel):
    """Schema to safely extract slot values from user conversation."""
    refund_order_id: Optional[str] = Field(default=None, description="The order ID, if mentioned.")
    refund_item_name: Optional[str] = Field(default=None, description="The specific product name, if mentioned.")
    refund_quantity: Optional[int] = Field(default=None, description="The number of items affected, if mentioned.")
    refund_reason: Optional[str] = Field(default=None, description="The reason for the refund, if mentioned.")

# ------------------------------------------------------------------
# 2. Nodes
# ------------------------------------------------------------------
def extract_slots_node(state: AgentState) -> dict:
    logger.info("Executing Refund Subgraph: extract_slots_node")
    last_message = state["messages"][-1].content

    llm = get_structured_llm(RefundExtraction)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Extract any refund details from the user's message. Only extract what is explicitly stated."),
        ("human", "{input}")
    ])

    result = (prompt | llm).invoke({"input": last_message})

    updates = {}
    if result.refund_order_id: updates["refund_order_id"] = result.refund_order_id
    if result.refund_item_name: updates["refund_item_name"] = result.refund_item_name
    if result.refund_quantity: updates["refund_quantity"] = result.refund_quantity
    if result.refund_reason: updates["refund_reason"] = result.refund_reason

    # Deterministic fallback: a bare number reply almost always means the
    # user is answering the quantity question, even if structured
    # extraction missed it on a short standalone digit/word.
    if "refund_quantity" not in updates and not state.get("refund_quantity"):
        stripped = last_message.strip().lower()
        number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        if stripped.isdigit():
            updates["refund_quantity"] = int(stripped)
        elif stripped in number_words:
            updates["refund_quantity"] = number_words[stripped]

    photo_match = re.search(r"\[attached photo: (\S+)\]", last_message)
    if photo_match:
        updates["refund_photo_url"] = photo_match.group(1)
    elif any(word in last_message.lower() for word in ["photo", "image", "pic", "attached"]):
        updates["refund_photo_url"] = "https://example.com/mock_damaged_item.jpg"

    return updates

def audit_slots_node(state: AgentState) -> dict:
    """
    Checks the 5 required refund slots.
    If any are missing, prompts the user and ends execution.
    """
    logger.info("Executing Refund Subgraph: audit_slots_node")

    if not state.get("refund_order_id"):
        return {"messages": [AIMessage(content="I can help with that refund. Could you please provide your Order ID?")]}

    if not state.get("refund_item_name"):
        return {"messages": [AIMessage(content="Which item from that order had the issue?")]}

    if not state.get("refund_quantity"):
        return {"messages": [AIMessage(content="How many of those items were affected?")]}

    if not state.get("refund_reason"):
        return {"messages": [AIMessage(content="Could you briefly describe the issue (e.g., damaged, missing, expired)?")]}

    if not state.get("refund_photo_url"):
        return {"messages": [AIMessage(content="Since this involves a damaged item, please upload a clear photo of the product (or just say 'here is a photo').")]}

    return {"current_intent": "execute_refund"}

def execute_refund_node(state: AgentState) -> dict:
    """
    Fires the DB tool to credit the user's wallet, clears the slots, and confirms.
    """
    logger.info("Executing Refund Subgraph: execute_refund_node")

    phone_number = state.get("user_profile", {}).get("phone_number", "whatsapp:+919876543210")
    order_id = state["refund_order_id"]
    item_name = state["refund_item_name"]
    quantity = int(state.get("refund_quantity", 1))

    # Prevent double-crediting the same order/item
    dup_check = json.loads(check_existing_refund.invoke({"order_id": order_id, "item_name": item_name}))
    if dup_check.get("already_refunded"):
        return {
            "messages": [AIMessage(content="Looks like this item was already refunded earlier — no further credit needed.")],
            "refund_order_id": None,
            "refund_item_name": None,
            "refund_quantity": None,
            "refund_reason": None,
            "refund_photo_url": None,
            "current_intent": "clarify"
        }

    # Look up the real item price instead of a flat amount
    lookup = json.loads(check_inventory.invoke({"query": item_name, "limit": 1}))
    unit_price = lookup["items"][0]["price"] if lookup.get("status") == "success" else 50.0
    refund_amount = unit_price * quantity

    process_refund_credit.invoke({
        "phone_number": phone_number,
        "amount": refund_amount,
        "order_id": order_id,
        "item_name": item_name,
    })

    msg = f"Success! I've processed a refund of ₹{refund_amount} for your {item_name}. The amount has been credited to your wallet balance."

    return {
        "messages": [AIMessage(content=msg)],
        "refund_order_id": None,
        "refund_item_name": None,
        "refund_quantity": None,
        "refund_reason": None,
        "refund_photo_url": None,
        "current_intent": "clarify"
    }

# ------------------------------------------------------------------
# 3. Conditional Routing Logic
# ------------------------------------------------------------------
def route_refund(state: AgentState) -> str:
    if state.get("current_intent") == "execute_refund":
        return "execute"
    return "wait_for_user"

# Compile the Subgraph
builder = StateGraph(AgentState)
builder.add_node("extract_slots", extract_slots_node)
builder.add_node("audit_slots", audit_slots_node)
builder.add_node("execute_refund", execute_refund_node)

builder.add_edge(START, "extract_slots")
builder.add_edge("extract_slots", "audit_slots")
builder.add_conditional_edges(
    "audit_slots",
    route_refund,
    {
        "execute": "execute_refund",
        "wait_for_user": END
    }
)
builder.add_edge("execute_refund", END)

refund_subgraph = builder.compile()