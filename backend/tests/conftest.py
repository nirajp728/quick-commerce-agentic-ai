import pytest
from typing import Optional
from backend.app.graph.state import AgentState


def make_state(**overrides) -> AgentState:
    """Builds a complete AgentState with sane defaults, overridden by kwargs."""
    base: AgentState = {
        "messages": [],
        "current_intent": None,
        "sentiment_score": 0.0,
        "is_handed_off": False,
        "user_profile": {},
        "thread_id": "test-thread-1",
-       "conversation_summary": None,
        "chat_cart": [],
        "refund_order_id": None,
        "refund_item_name": None,
        "refund_quantity": None,
        "refund_reason": None,
        "refund_photo_url": None,
        "rag_hallucination_retries": 0,
        "discovery_retries": 0,
        "qa_context": None,
        "discovery_items": [],
        "found_items": [],
        "discovery_original_query": None,
        "qa_search_query": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def state_factory():
    return make_state