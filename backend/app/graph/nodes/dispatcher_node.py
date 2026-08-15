import logging
from backend.app.graph.state import AgentState
from backend.app.graph.subgraphs.qa_graph import qa_subgraph
from backend.app.graph.subgraphs.discovery_graph import discovery_subgraph
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def dispatcher_node(state: AgentState) -> dict:
    """Invokes each subgraph the planner selected, passing its custom-formed
    query, and collects what each one gathered."""
    tasks = state.get("dispatch_tasks", [])
    collected = []
    updates = {}

    for task in tasks:
        target = task.get("target")
        query = task.get("query", "")

        if target == "qa":
            sub_state = {**state, "qa_search_query": query, "rag_hallucination_retries": 0, "gather_done": False}
            result = qa_subgraph.invoke(sub_state)
            collected.extend(result.get("gathered_context", []))

        elif target == "discovery":
            sub_state = {**state, "discovery_original_query": query, "discovery_retries": 0}
            result = discovery_subgraph.invoke(sub_state)
            collected.extend(result.get("gathered_context", []))
            if result.get("last_offered_items"):
                updates["last_offered_items"] = result["last_offered_items"]

    updates["gathered_context"] = collected
    updates["dispatch_tasks"] = []
    return updates