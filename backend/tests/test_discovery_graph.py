from backend.app.graph.subgraphs.discovery_graph import route_discovery, extract_ingredients_node
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage


def test_route_discovery_succeeds_with_full_match(state_factory):
    state = state_factory(discovery_items=["chicken", "butter"], found_items=[{"name": "x"}, {"name": "y"}])
    assert route_discovery(state) == "format_recipe"


def test_route_discovery_succeeds_with_half_match(state_factory):
    state = state_factory(discovery_items=["chicken", "butter"], found_items=[{"name": "x"}])
    assert route_discovery(state) == "format_recipe"


def test_route_discovery_retries_on_poor_match(state_factory):
    state = state_factory(discovery_items=["chicken", "butter", "cream"], found_items=[], discovery_retries=0)
    assert route_discovery(state) == "reflect_and_broaden"


def test_route_discovery_gives_up_after_max_retries(state_factory):
    state = state_factory(discovery_items=["chicken", "butter"], found_items=[], discovery_retries=2)
    assert route_discovery(state) == "format_recipe"


def test_route_discovery_treats_empty_request_as_success(state_factory):
    state = state_factory(discovery_items=[], found_items=[])
    assert route_discovery(state) == "format_recipe"


@patch("backend.app.graph.subgraphs.discovery_graph.get_llm")
def test_extract_ingredients_uses_original_query_on_retry(mock_get_llm, state_factory):
    """
    Regression test for the context-loss bug: on retry, extraction must
    use the preserved original request, not the reflection failure
    message that's now the latest item in `messages`.
    """
    mock_structured_llm = MagicMock()
    mock_chain_result = MagicMock()
    mock_chain_result.ingredients = ["chicken", "tomato"]
    mock_structured_llm.__or__ = lambda self, other: mock_structured_llm
    mock_structured_llm.invoke.return_value = mock_chain_result
    mock_get_llm.return_value.with_structured_output.return_value = mock_structured_llm

    state = state_factory(
        messages=[
            HumanMessage(content="I want to make butter chicken"),
            AIMessage(content="Failed to find: ['paneer']. Broaden the search terms to general categories."),
        ],
        discovery_original_query="I want to make butter chicken",
        discovery_retries=1,
    )

    extract_ingredients_node(state)

    invoked_input = mock_structured_llm.invoke.call_args[0][0]["input"]
    assert invoked_input == "I want to make butter chicken"
    assert invoked_input != "Failed to find: ['paneer']. Broaden the search terms to general categories."