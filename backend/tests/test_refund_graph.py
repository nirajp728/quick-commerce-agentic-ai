import json
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage

from backend.app.graph.subgraphs.refund_graph import (
    audit_slots_node,
    execute_refund_node,
    route_refund,
)


def test_audit_slots_asks_for_order_id_first(state_factory):
    """With nothing filled in, order_id must be the first thing asked for."""
    state = state_factory(messages=[HumanMessage(content="I want a refund")])
    result = audit_slots_node(state)
    assert "Order ID" in result["messages"][0].content


def test_audit_slots_asks_for_item_next(state_factory):
    state = state_factory(refund_order_id="ORD123")
    result = audit_slots_node(state)
    assert "item" in result["messages"][0].content.lower()


def test_audit_slots_marks_execute_when_all_slots_present(state_factory):
    state = state_factory(
        refund_order_id="ORD123",
        refund_item_name="Amul Butter",
        refund_quantity=1,
        refund_reason="damaged",
        refund_photo_url="https://example.com/photo.jpg",
    )
    result = audit_slots_node(state)
    assert result["current_intent"] == "execute_refund"


def test_route_refund_execute_vs_wait(state_factory):
    assert route_refund(state_factory(current_intent="execute_refund")) == "execute"
    assert route_refund(state_factory(current_intent="clarify")) == "wait_for_user"
    assert route_refund(state_factory(current_intent=None)) == "wait_for_user"


@patch("backend.app.graph.subgraphs.refund_graph.process_refund_credit")
@patch("backend.app.graph.subgraphs.refund_graph.check_inventory")
@patch("backend.app.graph.subgraphs.refund_graph.check_existing_refund")
def test_execute_refund_uses_real_item_price(mock_dup_check, mock_check_inventory, mock_process_credit, state_factory):
    """Refund amount must come from the item's actual price, not a flat rate."""
    mock_dup_check.invoke.return_value = json.dumps({"already_refunded": False})
    mock_check_inventory.invoke.return_value = json.dumps({
        "status": "success",
        "items": [{"product_id": "P002", "name": "Amul Butter (500g)", "price": 275}]
    })
    mock_process_credit.invoke.return_value = json.dumps({"status": "success", "new_balance": 725.0})

    state = state_factory(
        user_profile={"phone_number": "whatsapp:+919876543210"},
        refund_order_id="ORD123",
        refund_item_name="Amul Butter",
        refund_quantity=2,
        refund_reason="damaged",
        refund_photo_url="https://example.com/photo.jpg",
    )
    result = execute_refund_node(state)

    mock_process_credit.invoke.assert_called_once()
    call_args = mock_process_credit.invoke.call_args[0][0]
    assert call_args["amount"] == 550.0  # 275 * 2, not 50 * 2
    assert result["refund_order_id"] is None  # slots cleared after execution


@patch("backend.app.graph.subgraphs.refund_graph.process_refund_credit")
@patch("backend.app.graph.subgraphs.refund_graph.check_inventory")
@patch("backend.app.graph.subgraphs.refund_graph.check_existing_refund")
def test_execute_refund_blocks_duplicate(mock_dup_check, mock_check_inventory, mock_process_credit, state_factory):
    """Already-refunded order/item pairs must not be credited again."""
    mock_dup_check.invoke.return_value = json.dumps({"already_refunded": True})

    state = state_factory(
        user_profile={"phone_number": "whatsapp:+919876543210"},
        refund_order_id="ORD123",
        refund_item_name="Amul Butter",
        refund_quantity=1,
        refund_reason="damaged",
        refund_photo_url="https://example.com/photo.jpg",
    )
    result = execute_refund_node(state)

    mock_process_credit.invoke.assert_not_called()
    mock_check_inventory.invoke.assert_not_called()
    assert "already refunded" in result["messages"][0].content.lower()