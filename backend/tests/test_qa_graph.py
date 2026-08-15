from backend.app.graph.subgraphs.qa_graph import route_qa_cycle


def test_route_qa_cycle_ends_on_success(state_factory):
    state = state_factory(current_intent="answered", rag_hallucination_retries=0)
    assert route_qa_cycle(state) == "end"


def test_route_qa_cycle_retries_below_threshold(state_factory):
    state = state_factory(current_intent=None, rag_hallucination_retries=1)
    assert route_qa_cycle(state) == "retry"


def test_route_qa_cycle_falls_back_at_max_retries(state_factory):
    state = state_factory(current_intent=None, rag_hallucination_retries=3)
    assert route_qa_cycle(state) == "fallback"