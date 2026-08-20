import json
import logging
import re
from typing import Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_llm, get_structured_llm
from backend.app.tools.vector_tool import search_store_policies
from backend.app.tools.db_tools import check_order_history
from backend.app.tools.tavily_tool import web_search
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def retrieve_node(state: AgentState) -> dict:
    """
    Decides whether this is an order-history query or a policy/general
    query. Deliberately does NOT do the actual lookup here — that's
    split into two separate downstream nodes (order_lookup_node /
    policy_lookup_node), since a conditional edge reading a value this
    same node just returned proved unreliable in testing.
    """
    logger.info("QA Subgraph: Retrieving local context...")
    query = state.get("qa_search_query") or state["messages"][-1].content

    order_keywords = ["order", "orders", "purchase", "bought", "history", "delivered", "shipment"]
    is_order_query = any(kw in query.lower() for kw in order_keywords)
    logger.info(f"QA Subgraph: is_order_query={is_order_query} for query={query!r}")

    return {"qa_search_query": query, "_is_order_query": is_order_query}

def route_after_retrieve(state: AgentState) -> str:
    return "order_lookup" if state.get("_is_order_query") else "policy_lookup"

def order_lookup_node(state: AgentState) -> dict:
    """Direct Mongo lookup for order-history questions. Forces
    crag_grade='correct' so grading is skipped entirely."""
    phone_number = state.get("user_profile", {}).get("phone_number", "")
    logger.info(f"QA Subgraph: order_lookup_node phone_number={phone_number!r}")
    docs = check_order_history.invoke({"phone_number": phone_number})
    return {"qa_context": docs, "crag_grade": "correct"}

def policy_lookup_node(state: AgentState) -> dict:
    """Vector search for policy/general questions — goes through normal
    CRAG grading afterward."""
    query = state.get("qa_search_query", "")
    docs = search_store_policies.invoke(query)
    return {"qa_context": docs}

def route_after_lookup(state: AgentState) -> str:
    if state.get("crag_grade") == "correct":
        return "generate"
    return "grade"

class CRAGGrade(BaseModel):
    grade: Literal["correct", "ambiguous", "incorrect"] = Field(
        description="'correct' if the retrieved context fully and clearly answers the query. "
                    "'ambiguous' if it's partially relevant but incomplete. "
                    "'incorrect' if it's unrelated or empty."
    )

def grade_node(state: AgentState) -> dict:
    """The CRAG retrieval evaluator — grades local retrieval quality
    before deciding whether web search is needed at all. Only reached
    for policy/general questions, never order-history lookups."""
    logger.info("QA Subgraph: Grading local retrieval...")
    query = state.get("qa_search_query", "")
    context = state.get("qa_context", "")

    grade: CRAGGrade = (
        ChatPromptTemplate.from_messages([
            ("system", "Query: {query}\nRetrieved context: {context}\n\nGrade how well this context "
                       "answers the query."),
            ("human", "Grade it."),
        ]) | get_structured_llm(CRAGGrade)
    ).invoke({"query": query, "context": context})

    logger.info(f"QA Subgraph: CRAG grade = {grade.grade}")
    return {"crag_grade": grade.grade}

def route_crag(state: AgentState) -> str:
    grade = state.get("crag_grade", "incorrect")
    return "generate" if grade == "correct" else "web_search"

def web_search_node(state: AgentState) -> dict:
    logger.info("QA Subgraph: Retrieval insufficient, searching the web...")
    query = state.get("qa_search_query", "")
    result = json.loads(web_search.invoke({"query": query}))
    return {"web_search_results": result.get("context", "")}

def _order_json_to_text(raw: str, requested_order_id: str = "") -> str:
    """
    Converts check_order_history's raw JSON payload into plain prose
    before handing it to the generation LLM. If a specific order ID was
    asked about, filters down to just that order — handing the model
    every order in the account and expecting it to find the right one by
    ID-matching inside a text blob proved unreliable (it would claim "no
    data found" even when the correct order was present, just buried
    among others).
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

    if parsed.get("status") == "no_orders_found":
        return "No matching order was found for this user."

    if parsed.get("status") == "success" and parsed.get("orders"):
        orders = parsed["orders"]

        if requested_order_id:
            matching = [o for o in orders if o.get("order_id", "").upper() == requested_order_id.upper()]
            if matching:
                orders = matching
            else:
                return f"No order with ID {requested_order_id} was found for this user."

        lines = []
        for order in orders:
            items_text = ", ".join(
                f"{i['name']} (qty {i['qty']}, ₹{i['price']})" for i in order.get("items", [])
            )
            lines.append(
                f"Order {order['order_id']}: {items_text}. "
                f"Total: ₹{order['total']}. Status: {order.get('status', 'Unknown')}."
            )
        return "\n".join(lines)

    return raw

def generate_node(state: AgentState) -> dict:
    """Generation step, using exactly the context the CRAG grade calls
    for. Order-history context is filtered to the specific requested
    order (if one was named) and converted to plain text first."""
    logger.info("QA Subgraph: Generating answer...")
    grade = state.get("crag_grade")
    local_raw = state.get("qa_context", "")
    query = state.get("qa_search_query", "")

    order_id_match = re.search(r'\bORD[A-Z0-9]{6,}\b', query)
    requested_order_id = order_id_match.group(0) if order_id_match else ""

    local = _order_json_to_text(local_raw, requested_order_id)
    web = state.get("web_search_results", "")

    if grade == "correct":
        context = local
    elif grade == "ambiguous":
        context = f"Store data: {local}\n\nWeb search results: {web}"
    else:  # incorrect
        context = f"Web search results: {web}"

    logger.info(f"QA Subgraph: generate_node grade={grade!r}, requested_order_id={requested_order_id!r}, context={context[:300]!r}")

    response = (
    ChatPromptTemplate.from_messages([
        ("system", "You are answering a question using the context below. The context contains the "
                   "factual answer if one exists. Read it carefully and state what it says directly. "
                   "Context:\n{context}"),
        ("human", "{query}"),
    ]) | get_llm()
    ).invoke({"context": context, "query": query}).content

    if isinstance(response, list):
        response = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in response)

    return {
        "gathered_context": [response.strip()],
        "qa_search_query": None,
        "crag_grade": None,
        "web_search_results": None,
        "qa_context": None,
        "_is_order_query": None,
    }

# Compile the Subgraph
builder = StateGraph(AgentState)
builder.add_node("retrieve", retrieve_node)
builder.add_node("order_lookup", order_lookup_node)
builder.add_node("policy_lookup", policy_lookup_node)
builder.add_node("grade", grade_node)
builder.add_node("web_search", web_search_node)
builder.add_node("generate", generate_node)

builder.add_edge(START, "retrieve")
builder.add_conditional_edges("retrieve", route_after_retrieve, {"order_lookup": "order_lookup", "policy_lookup": "policy_lookup"})
builder.add_conditional_edges("order_lookup", route_after_lookup, {"generate": "generate", "grade": "grade"})
builder.add_edge("policy_lookup", "grade")
builder.add_conditional_edges("grade", route_crag, {"generate": "generate", "web_search": "web_search"})
builder.add_edge("web_search", "generate")
builder.add_edge("generate", END)

qa_subgraph = builder.compile()