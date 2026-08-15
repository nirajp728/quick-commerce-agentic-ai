import logging
from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_llm, get_structured_llm
from backend.app.tools.vector_tool import search_store_policies
from backend.app.tools.db_tools import check_order_history
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def retrieve_node(state: AgentState) -> dict:
    logger.info("QA Subgraph: Retrieving context...")
    query = state.get("qa_search_query") or state["messages"][-1].content

    order_keywords = ["order", "orders", "purchase", "bought", "history", "delivered", "shipment"]
    if any(kw in query.lower() for kw in order_keywords):
        phone_number = state.get("user_profile", {}).get("phone_number", "")
        docs = check_order_history.invoke({"phone_number": phone_number})
    else:
        docs = search_store_policies.invoke(query)

    return {"qa_context": docs, "qa_search_query": query}

class RelevanceGrade(BaseModel):
    is_relevant: bool = Field(description="True if this context actually answers the query.")

def grade_and_generate_node(state: AgentState) -> dict:
    """Grades whether retrieved context is relevant. On success, hands back
    the RAW context — the shared answer_node does the actual writing now,
    so this node no longer generates a polished response itself."""
    logger.info("QA Subgraph: Grading relevance...")
    query = state.get("qa_search_query") or state["messages"][-1].content
    context = state.get("qa_context", "")
    retries = state.get("rag_hallucination_retries", 0)

    grade: RelevanceGrade = (
        ChatPromptTemplate.from_messages([
            ("system", "Query: {query}\nContext: {context}\n\nDoes this context actually answer the query?"),
            ("human", "Grade it."),
        ]) | get_structured_llm(RelevanceGrade)
    ).invoke({"query": query, "context": context})

    if not grade.is_relevant:
        rewrite = (
            ChatPromptTemplate.from_messages([
                ("system", "The search for \"{query}\" found nothing relevant. Rewrite it as a short, "
                           "differently-worded query. Reply with ONLY the rewritten query."),
                ("human", "Rewrite it."),
            ]) | get_llm()
        ).invoke({"query": query}).content
        if isinstance(rewrite, list):
            rewrite = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in rewrite)
        return {"rag_hallucination_retries": retries + 1, "qa_search_query": rewrite.strip(), "gather_done": False}

    return {"gathered_context": [context], "gather_done": True, "rag_hallucination_retries": 0, "qa_search_query": None}

def route_qa_cycle(state: AgentState) -> str:
    if state.get("gather_done"):
        return "end"
    if state.get("rag_hallucination_retries", 0) >= 3:
        logger.warning("QA Subgraph: Maximum retries reached. Falling back.")
        return "fallback"
    return "retry"

def fallback_node(state: AgentState) -> dict:
    query = state.get("qa_search_query") or state["messages"][-1].content
    return {
        "gathered_context": [f"No relevant policy or order information could be found for: \"{query}\"."],
        "gather_done": True,
        "rag_hallucination_retries": 0,
        "qa_search_query": None,
    }

builder = StateGraph(AgentState)
builder.add_node("retrieve", retrieve_node)
builder.add_node("grade_and_generate", grade_and_generate_node)
builder.add_node("fallback", fallback_node)

builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", "grade_and_generate")
builder.add_conditional_edges("grade_and_generate", route_qa_cycle, {"end": END, "retry": "retrieve", "fallback": "fallback"})
builder.add_edge("fallback", END)

qa_subgraph = builder.compile()