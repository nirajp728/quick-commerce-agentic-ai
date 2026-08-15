import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.mongodb import MongoDBSaver

from backend.app.config import settings
from backend.app.db.mongo_client import db_connection
from backend.app.graph.state import AgentState

from backend.app.graph.nodes.router_planner import router_node
from backend.app.graph.nodes.handoff_node import handoff_node
from backend.app.graph.nodes.aggregator import aggregator_node
from backend.app.graph.nodes.planner_node import planner_node
from backend.app.graph.nodes.dispatcher_node import dispatcher_node
from backend.app.graph.nodes.answer_node import answer_node

from backend.app.graph.subgraphs.cart_graph import cart_subgraph
from backend.app.graph.subgraphs.refund_graph import refund_subgraph

logger = logging.getLogger(settings.APP_NAME)

def route_intent(state: AgentState) -> str:
    """Reads the state intent and directs traffic. cart/refund stay direct
    (mutation/transaction flows); qa/discovery both route through the
    planner, which decides the actual gathering steps needed."""
    if state.get("is_handed_off"):
        return "handoff"

    intent = state.get("current_intent")
    if intent == "cart": return "cart_graph"
    if intent == "refund": return "refund_graph"
    if intent in ("qa", "discovery"): return "planner"
    if intent == "handoff": return "handoff"
    return "clarify_and_wait"

def build_master_graph():
    builder = StateGraph(AgentState)

    builder.add_node("router", router_node)
    builder.add_node("handoff", handoff_node)
    builder.add_node("aggregator", aggregator_node)
    builder.add_node("cart_graph", cart_subgraph)
    builder.add_node("refund_graph", refund_subgraph)
    builder.add_node("planner", planner_node)
    builder.add_node("dispatcher", dispatcher_node)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_intent,
        {
            "cart_graph": "cart_graph",
            "refund_graph": "refund_graph",
            "planner": "planner",
            "handoff": "handoff",
            "clarify_and_wait": "aggregator"
        }
    )

    builder.add_edge("cart_graph", "aggregator")
    builder.add_edge("refund_graph", "aggregator")
    builder.add_edge("planner", "dispatcher")
    builder.add_edge("dispatcher", "answer")
    builder.add_edge("answer", "aggregator")

    builder.add_edge("aggregator", END)
    builder.add_edge("handoff", END)

    return builder

master_graph = build_master_graph().compile()

def get_compiled_graph_with_checkpointer():
    if not db_connection.sync_client:
        raise ConnectionError("MongoDB sync_client not initialized.")
    checkpointer = MongoDBSaver(db_connection.sync_client)
    return build_master_graph().compile(checkpointer=checkpointer, interrupt_after=["handoff"])