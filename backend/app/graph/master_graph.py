import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.mongodb import MongoDBSaver

from backend.app.config import settings
from backend.app.db.mongo_client import db_connection
from backend.app.graph.state import AgentState

from backend.app.graph.nodes.ingestion_node import ingestion_node
from backend.app.graph.nodes.clarification_node import clarification_node, route_after_clarification
from backend.app.graph.nodes.planner_node import planner_node
from backend.app.graph.nodes.dispatcher_node import dispatcher_node, route_after_dispatch
from backend.app.graph.nodes.answer_node import answer_node
from backend.app.graph.nodes.handoff_node import handoff_node
from backend.app.graph.nodes.aggregator import aggregator_node

logger = logging.getLogger(settings.APP_NAME)

def build_master_graph():
    """
    Flow: ingestion (extract media) -> clarification (loop, max 4 attempts,
    handles topic-switch interrupt stack) -> planner (picks cart/refund/qa/
    discovery, possibly multiple) -> dispatcher (invokes them) -> answer
    (only if qa/discovery gathered facts) -> aggregator -> END.
    Handoff is reachable from clarification (explicit request, sentiment,
    or 4 failed clarification attempts) and pauses via interrupt_after.
    """
    builder = StateGraph(AgentState)

    builder.add_node("ingestion", ingestion_node)
    builder.add_node("clarification", clarification_node)
    builder.add_node("planner", planner_node)
    builder.add_node("dispatcher", dispatcher_node)
    builder.add_node("answer", answer_node)
    builder.add_node("handoff", handoff_node)
    builder.add_node("aggregator", aggregator_node)

    builder.add_edge(START, "ingestion")
    builder.add_edge("ingestion", "clarification")

    builder.add_conditional_edges(
        "clarification",
        route_after_clarification,
        {
            "planner": "planner",
            "handoff": "handoff",
            "end_turn": "aggregator",
        }
    )

    builder.add_edge("planner", "dispatcher")

    builder.add_conditional_edges(
        "dispatcher",
        route_after_dispatch,
        {
            "answer": "answer",
            "aggregator": "aggregator",
        }
    )

    builder.add_edge("answer", "aggregator")
    builder.add_edge("aggregator", END)
    builder.add_edge("handoff", END)

    return builder

master_graph = build_master_graph().compile()

def get_compiled_graph_with_checkpointer():
    """
    Returns the compiled graph attached to the MongoDB checkpointer.
    Must be called after FastAPI startup when DB connections are active.
    """
    if not db_connection.sync_client:
        raise ConnectionError("MongoDB sync_client not initialized.")

    checkpointer = MongoDBSaver(db_connection.sync_client)

    return build_master_graph().compile(
        checkpointer=checkpointer,
        interrupt_after=["handoff"]
    )