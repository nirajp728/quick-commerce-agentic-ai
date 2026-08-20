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
from backend.app.tools.db_tools import validate_refund_request, process_refund_credit
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
    """
    Parses the user's latest message and extracts any mentioned refund slots
    without overwriting existing ones. Attached-image descriptions
    ('[image shows: ...]') are explicitly excluded as a source for any
    slot field, including refund_item_name — an image is photo evidence
    only, captured separately as refund_photo_url. Without this
    exclusion, a real bug occurred: an unrelated laptop photo attached
    during the photo-upload step got its vision description ("ASUS
    Expertbook") extracted as the refund item name, and would have been
    credited had validate_refund_request not caught it downstream.
    """
    logger.info("Executing Refund Subgraph: extract_slots_node")
    last_message = state["messages"][-1].content

    llm = get_structured_llm(RefundExtraction)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Extract any refund details from the user's message. Only extract what is explicitly "
                   "stated as the user's own words describing their refund request — order ID, item name, "
                   "quantity, and reason. If the message contains an '[image shows: ...]' description from "
                   "an attached photo, that describes photo evidence only — do NOT extract refund_item_name "
                   "or any other field from that image description; only use it to confirm a photo was "
                   "provided (a photo URL is captured separately, not through this extraction)."),
        ("human", "{input}")
    ])

    result = (prompt | llm).invoke({"input": last_message})

    updates = {}
    if result.refund_order_id: updates["refund_order_id"] = result.refund_order_id
    if result.refund_item_name: updates["refund_item_name"] = result.refund_item_name
    if result.refund_quantity: updates["refund_quantity"] = result.refund_quantity
    if result.refund_reason: updates["refund_reason"] = result.refund_reason

    stripped = last_message.strip().lower()
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    if "refund_quantity" not in updates and not state.get("refund_quantity"):
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
    Validates the refund against real order data (does the order exist,
    was this item actually in it, has it already been refunded), then
    credits the wallet using the order's REAL recorded price — not a
    separate, potentially divergent inventory lookup.
    """
    logger.info("Executing Refund Subgraph: execute_refund_node")

    phone_number = state.get("user_profile", {}).get("phone_number", "whatsapp:+919876543210")
    order_id = state["refund_order_id"]
    item_name = state["refund_item_name"]
    quantity = int(state.get("refund_quantity", 1))

    validation = json.loads(validate_refund_request.invoke({
        "phone_number": phone_number,
        "order_id": order_id,
        "item_name": item_name,
    }))

    if not validation.get("valid"):
        logger.warning(f"Refund validation failed: {validation.get('reason')}")
        return {
            "messages": [AIMessage(content=validation.get("message", "I couldn't validate that refund request."))],
            "refund_order_id": None,
            "refund_item_name": None,
            "refund_quantity": None,
            "refund_reason": None,
            "refund_photo_url": None,
            "current_intent": "clarify"
        }

    unit_price = validation["unit_price"]
    matched_item_name = validation["matched_item_name"]
    refund_amount = unit_price * quantity

    process_refund_credit.invoke({
        "phone_number": phone_number,
        "amount": refund_amount,
        "order_id": order_id,
        "item_name": matched_item_name,
    })

    msg = f"Success! I've processed a refund of ₹{refund_amount} for your {matched_item_name}. The amount has been credited to your wallet balance."

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