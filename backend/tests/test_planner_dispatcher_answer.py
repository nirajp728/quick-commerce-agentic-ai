from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from backend.app.graph.master_graph import route_intent
from backend.app.graph.nodes.dispatcher_node import dispatcher_node
from backend.app.graph.nodes.answer_node import answer_node


def test_route_intent_maps_qa_and_discovery_to_planner(state_factory):
    """Both qa and discovery must route through the planner, not directly
    to their old subgraph names — this was the core routing change of the
    planner/dispatcher rebuild."""
    assert route_intent(state_factory(current_intent="qa")) == "planner"
    assert route_intent(state_factory(current_intent="discovery")) == "planner"


def test_route_intent_cart_and_refund_stay_direct(state_factory):
    """Cart and refund must NOT go through the planner — they're
    mutation/transaction flows, not gather-then-answer questions."""
    assert route_intent(state_factory(current_intent="cart")) == "cart_graph"
    assert route_intent(state_factory(current_intent="refund")) == "refund_graph"


@patch("backend.app.graph.nodes.dispatcher_node.discovery_subgraph")
@patch("backend.app.graph.nodes.dispatcher_node.qa_subgraph")
def test_dispatcher_invokes_discovery_for_availability_task(mock_qa, mock_discovery, state_factory):
    """A planner task targeting 'discovery' must actually invoke the
    discovery subgraph with the planner's custom-formed query, not the
    qa subgraph."""
    mock_discovery.invoke.return_value = {
        "gathered_context": ["Store availability check for \"amul butter\": In stock:\n- Amul Butter (500g): ₹275"],
        "last_offered_items": [{"product_id": "P002", "name": "Amul Butter (500g)", "price": 275}],
    }

    state = state_factory(dispatch_tasks=[{"target": "discovery", "query": "amul butter"}])
    result = dispatcher_node(state)

    mock_discovery.invoke.assert_called_once()
    called_sub_state = mock_discovery.invoke.call_args[0][0]
    assert called_sub_state["discovery_original_query"] == "amul butter"
    mock_qa.invoke.assert_not_called()
    assert "Amul Butter" in result["gathered_context"][0]
    assert result["last_offered_items"][0]["name"] == "Amul Butter (500g)"


@patch("backend.app.graph.nodes.dispatcher_node.discovery_subgraph")
@patch("backend.app.graph.nodes.dispatcher_node.qa_subgraph")
def test_dispatcher_invokes_qa_for_policy_task(mock_qa, mock_discovery, state_factory):
    """A planner task targeting 'qa' must invoke the qa subgraph, not discovery."""
    mock_qa.invoke.return_value = {"gathered_context": ["Refund policy: 24h window, photo required."]}

    state = state_factory(dispatch_tasks=[{"target": "qa", "query": "refund policy"}])
    result = dispatcher_node(state)

    mock_qa.invoke.assert_called_once()
    called_sub_state = mock_qa.invoke.call_args[0][0]
    assert called_sub_state["qa_search_query"] == "refund policy"
    mock_discovery.invoke.assert_not_called()
    assert "Refund policy" in result["gathered_context"][0]


def test_dispatcher_handles_empty_task_list(state_factory):
    """If the planner decides no store data is needed, dispatcher must
    invoke nothing and return an empty gathered_context, not error."""
    state = state_factory(dispatch_tasks=[])
    result = dispatcher_node(state)
    assert result["gathered_context"] == []


@patch("backend.app.graph.nodes.answer_node.get_llm")
def test_answer_node_uses_gathered_context_when_present(mock_get_llm, state_factory):
    """When gathered_context has data, it must be passed into the prompt
    so the answer can incorporate real store facts."""
    mock_llm = MagicMock()
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = AIMessage(content="We have Amul Butter for ₹275.")
    mock_llm.__or__ = lambda self, other: mock_chain
    mock_get_llm.return_value = mock_llm

    state = state_factory(
        messages=[HumanMessage(content="do you have amul butter?")],
        gathered_context=["Store availability check: In stock: Amul Butter (500g): ₹275"],
    )
    result = answer_node(state)

    invoked_gathered = mock_chain.invoke.call_args[0][0]["gathered"]
    assert "Amul Butter" in invoked_gathered
    assert result["gathered_context"] == []  # cleared after use


@patch("backend.app.graph.nodes.answer_node.get_llm")
def test_answer_node_handles_empty_gathered_context(mock_get_llm, state_factory):
    """With nothing gathered, the prompt should receive an empty string,
    not a placeholder like '(nothing gathered)' that could bias the model
    toward claiming it has no general knowledge either."""
    mock_llm = MagicMock()
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = AIMessage(content="Pav bhaji needs potatoes, peas, and pav bhaji masala.")
    mock_llm.__or__ = lambda self, other: mock_chain
    mock_get_llm.return_value = mock_llm

    state = state_factory(
        messages=[HumanMessage(content="what are pav bhaji ingredients?")],
        gathered_context=[],
    )
    answer_node(state)

    invoked_gathered = mock_chain.invoke.call_args[0][0]["gathered"]
    assert invoked_gathered == ""