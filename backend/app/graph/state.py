import operator
from typing import Annotated, TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    The master state object that flows through the Quick-Commerce LangGraph.
    Every node reads from and writes updates to this dictionary.
    """

    # ------------------------------------------------------------------
    # 1. Core Conversation & Routing State
    # ------------------------------------------------------------------
    messages: Annotated[list[BaseMessage], add_messages]
    current_intent: Optional[str]
    sentiment_score: float
    is_handed_off: bool
    user_profile: Optional[Dict[str, Any]]
    thread_id: Optional[str]  # Needed so handoff_node knows which chat to alert admins about

    # ------------------------------------------------------------------
    # 2. State Mutation Pattern (Ephemeral Cart)
    # ------------------------------------------------------------------
    chat_cart: List[Dict[str, Any]]

    # ------------------------------------------------------------------
    # 3. Macro-Loop / Slot-Filling State (Refund Process)
    # ------------------------------------------------------------------
    refund_order_id: Optional[str]
    refund_item_name: Optional[str]
    refund_quantity: Optional[int]
    refund_reason: Optional[str]
    refund_photo_url: Optional[str]

    # ------------------------------------------------------------------
    # 4. Micro-Loop Guardrails (True Graph Cycles)
    # ------------------------------------------------------------------
    rag_hallucination_retries: int
    discovery_retries: int

    # ------------------------------------------------------------------
    # 5. Temporary Intra-Turn State
    # ------------------------------------------------------------------
    qa_context: Optional[str]
    discovery_items: List[str]
    found_items: List[Dict[str, Any]]
    discovery_original_query: Optional[str]  # Preserves the user's original ask across reflect/retry loops
    qa_search_query: Optional[str]  # Tracks the current (possibly rewritten) search query across QA retries
    last_offered_items: List[Dict[str, Any]]  # Items just shown to the user, so cart can resolve "add this/these"

    # ------------------------------------------------------------------
    # 6. Planner / Dispatcher / Answer Pattern (cart, refund, qa, discovery gathering)
    # ------------------------------------------------------------------
    dispatch_tasks: List[Dict[str, Any]]  # Planner's chosen {target, query} pairs
    gathered_context: List[str]           # Raw facts collected by dispatched subgraphs
    gather_done: Optional[bool]           # QA subgraph's own internal loop-exit signal
    clarification_attempts: int
    _dispatch_produced_message: Optional[bool]  # True if cart/refund produced their own real message this turn — blocks answer_node from also running and possibly fabricating a transactional outcome

    # ------------------------------------------------------------------
    # 7. Ingestion Node I/O
    # ------------------------------------------------------------------
    attachment_data: Optional[str]          # Base64-encoded upload, consumed and cleared by ingestion_node
    attachment_content_type: Optional[str]

    # ------------------------------------------------------------------
    # 8. CRAG (QA Subgraph)
    # ------------------------------------------------------------------
    crag_grade: Optional[str]            # "correct" | "ambiguous" | "incorrect"
    web_search_results: Optional[str]    # Tavily output, only populated on ambiguous/incorrect grades
    skip_crag_grading: Optional[bool]    # Legacy field, no longer read by qa_graph.py
    _is_order_query: Optional[bool]      # Passes retrieve_node's routing decision to route_after_retrieve