import logging
from langchain_core.messages import AIMessage

from backend.app.graph.state import AgentState
from backend.app.graph.subgraphs.qa_graph import qa_subgraph
from backend.app.graph.subgraphs.discovery_graph import discovery_subgraph
from backend.app.graph.subgraphs.cart_graph import cart_subgraph
from backend.app.graph.subgraphs.refund_graph import refund_subgraph
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

REFUND_SLOT_FIELDS = ["refund_order_id", "refund_item_name", "refund_quantity", "refund_reason", "refund_photo_url"]
LOOKUP_KEYWORDS = ["item", "items", "what was", "what were", "list", "order detail", "order history", "what did i order", "what did i buy"]

def dispatcher_node(state: AgentState) -> dict:
    """
    Invokes each subgraph the planner selected. Every subgraph gets an
    explicit shallow copy of state, never the shared state object directly.

    Deterministic safety net: if refund is in progress but the planner
    didn't dispatch a 'qa' task, and the message contains lookup-style
    keywords, force a 'qa' order-lookup task in addition.

    Cart/refund messages are transactional and authoritative — if either
    produces its own message this turn, _dispatch_produced_message is set
    so route_after_dispatch knows to skip answer_node entirely for this
    turn. Letting answer_node also run in that case previously caused a
    real, serious bug: it fabricated a "refund completed" message from
    conversational context even though no refund had actually executed.
    """
    tasks = state.get("dispatch_tasks", [])

    refund_in_progress = bool(state.get("refund_order_id")) and any(
        not state.get(f) for f in REFUND_SLOT_FIELDS
    )
    has_qa_task = any(t.get("target") == "qa" for t in tasks)
    last_message = state["messages"][-1].content.lower() if state.get("messages") else ""

    if refund_in_progress and not has_qa_task and any(kw in last_message for kw in LOOKUP_KEYWORDS):
        logger.info("Dispatcher: forcing qa order-lookup task (planner missed it, keyword fallback fired).")
        tasks = tasks + [{"target": "qa", "query": f"What items were in order {state.get('refund_order_id')}?"}]

    collected_context = []
    new_messages = []
    updates = {}
    refund_was_dispatched = False
    dispatch_produced_message = False

    for task in tasks:
        target = task.get("target")
        query = task.get("query", "")

        if target == "qa":
            sub_state = {**state, "qa_search_query": query, "rag_hallucination_retries": 0,
                         "crag_grade": None, "web_search_results": None}
            result = qa_subgraph.invoke(sub_state)
            collected_context.extend(result.get("gathered_context", []))

        elif target == "discovery":
            sub_state = {**state, "discovery_original_query": query, "discovery_retries": 0}
            result = discovery_subgraph.invoke(sub_state)
            collected_context.extend(result.get("gathered_context", []))
            if result.get("last_offered_items"):
                updates["last_offered_items"] = result["last_offered_items"]

        elif target == "cart":
            sub_state = {**state}
            result = cart_subgraph.invoke(sub_state)
            updates["chat_cart"] = result.get("chat_cart", state.get("chat_cart", []))
            if result.get("last_offered_items") is not None:
                updates["last_offered_items"] = result["last_offered_items"]
            if result.get("messages"):
                new_messages.extend(result["messages"])
                dispatch_produced_message = True

        elif target == "refund":
            refund_was_dispatched = True
            sub_state = {**state}
            result = refund_subgraph.invoke(sub_state)
            for key in REFUND_SLOT_FIELDS + ["current_intent"]:
                if key in result:
                    updates[key] = result[key]
            if result.get("messages"):
                new_messages.extend(result["messages"])
                dispatch_produced_message = True

    # Deterministic reminder: no LLM judgment, just a fact check against
    # state. Only fires when refund produced no message of its own this
    # turn (i.e. it genuinely wasn't touched), so it never overwrites a
    # real refund message.
    effective_order_id = updates.get("refund_order_id", state.get("refund_order_id"))
    if effective_order_id and not refund_was_dispatched:
        missing = [f for f in REFUND_SLOT_FIELDS if not (updates.get(f, state.get(f)))]
        if missing:
            reminder = f"\n\n(By the way, you still have a refund in progress for order {effective_order_id} — let me know when you're ready to continue with that.)"
            if new_messages:
                new_messages[-1] = AIMessage(content=new_messages[-1].content + reminder)
            elif collected_context:
                collected_context.append(f"[Reminder to include in your reply: mention there's a refund still pending for order {effective_order_id}.]")

    updates["gathered_context"] = collected_context
    updates["dispatch_tasks"] = []
    updates["_dispatch_produced_message"] = dispatch_produced_message
    if new_messages:
        updates["messages"] = new_messages
    return updates

def route_after_dispatch(state: AgentState) -> str:
    """
    answer_node only runs for pure informational gathering (qa/discovery)
    with no transactional message already produced this turn. If cart or
    refund already gave the user a real, authoritative message, that
    message stands as-is — answer_node must not also run and potentially
    fabricate or contradict it.
    """
    if state.get("_dispatch_produced_message"):
        return "aggregator"
    return "answer" if state.get("gathered_context") else "aggregator"