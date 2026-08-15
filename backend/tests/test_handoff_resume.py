from backend.app.graph.master_graph import build_master_graph


def test_handoff_uses_interrupt_after_not_before():
    """
    Regression test for the resume bug: interrupt must be configured as
    interrupt_after=['handoff'], not interrupt_before. interrupt_before
    would mean the handoff node hasn't run yet when the graph pauses, so
    resuming would re-execute it and immediately re-set is_handed_off=True
    instead of continuing past it.
    """
    checkpointer = None  # compiling without a checkpointer is fine for inspecting config
    graph = build_master_graph().compile(interrupt_after=["handoff"])

    assert "handoff" in graph.interrupt_after_nodes
    assert "handoff" not in graph.interrupt_before_nodes