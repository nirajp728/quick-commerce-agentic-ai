import pytest
from langchain_core.messages import HumanMessage
from backend.app.graph.nodes.router_planner import router_node
from backend.app.graph.state import AgentState

def test_router_node_fallback_on_empty_messages():
    """Validates that the router node handles empty states gracefully without throwing errors."""
    empty_state: AgentState = {
        "messages": [],
        "current_intent": None,
        "sentiment_score": 0.0,
        "is_handed_off": False,
        "user_profile": {},
        "chat_cart": [],
        "refund_order_id": None,
        "refund_item_name": None,
        "refund_quantity": None,
        "refund_reason": None,
        "refund_photo_url": None,
        "db_search_retries": 0,
        "rag_hallucination_retries": 0,
        "discovery_retries": 0,
        "qa_context": None,
        "discovery_items": [],
        "found_items": []
    }
    
    result = router_node(empty_state)
    assert result["current_intent"] == "clarify"
    assert result["sentiment_score"] == 0.0

def test_router_node_live_classification():
    """
    Tests actual intent classification using the LLM. 
    Skips automatically if GEMINI_API_KEY is missing from the test environment.
    """
    import os
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not configured. Skipping live LLM routing test.")

    state: AgentState = {
        "messages": [HumanMessage(content="I want to buy 2 packs of Amul Butter")],
        "current_intent": None,
        "sentiment_score": 0.0,
        "is_handed_off": False,
        "user_profile": {},
        "chat_cart": [],
        "refund_order_id": None,
        "refund_item_name": None,
        "refund_quantity": None,
        "refund_reason": None,
        "refund_photo_url": None,
        "db_search_retries": 0,
        "rag_hallucination_retries": 0,
        "discovery_retries": 0,
        "qa_context": None,
        "discovery_items": [],
        "found_items": []
    }
    
    result = router_node(state)
    assert result["current_intent"] == "cart"
    assert isinstance(result["sentiment_score"], float)