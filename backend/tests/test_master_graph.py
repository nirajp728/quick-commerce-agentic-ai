from backend.app.graph.master_graph import route_intent


def test_route_intent_handoff_flag_takes_priority(state_factory):
    """is_handed_off must win even if current_intent says something else."""
    state = state_factory(is_handed_off=True, current_intent="cart")
    assert route_intent(state) == "handoff"


def test_route_intent_maps_each_known_intent(state_factory):
    expected = {
        "cart": "cart_graph",
        "refund": "refund_graph",
        "qa": "qa_graph",
        "discovery": "discovery_graph",
        "handoff": "handoff",
    }
    for intent, target in expected.items():
        state = state_factory(current_intent=intent)
        assert route_intent(state) == target


def test_route_intent_falls_back_to_clarify(state_factory):
    state = state_factory(current_intent="clarify")
    assert route_intent(state) == "clarify_and_wait"

    state = state_factory(current_intent=None)
    assert route_intent(state) == "clarify_and_wait"

    state = state_factory(current_intent="not_a_real_intent")
    assert route_intent(state) == "clarify_and_wait"