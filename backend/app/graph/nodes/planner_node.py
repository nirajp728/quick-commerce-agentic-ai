import logging
from typing import List, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_structured_llm
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

class DispatchTask(BaseModel):
    target: Literal["qa", "discovery"] = Field(
        description="'qa' for store policies or the user's own order history; "
                    "'discovery' for product availability, prices, or recipe/ingredient lookups."
    )
    query: str = Field(description="A clean, self-contained query for that subgraph — rewritten, not copied verbatim.")

class DispatchPlan(BaseModel):
    tasks: List[DispatchTask] = Field(description="Gathering tasks needed to answer the user's CURRENT question. Usually just one.")

def _build_transcript(messages) -> str:
    return "\n".join(f"{'User' if m.type == 'human' else 'Assistant'}: {m.content}" for m in messages)

def planner_node(state: AgentState) -> dict:
    """Decides which subgraph(s) to invoke and what to ask each, based on
    the full conversation — distinguishing the live question from anything
    already resolved earlier in the thread."""
    logger.info("Executing Planner Node...")
    transcript = _build_transcript(state.get("messages", []))

    system_prompt = """You are a planning agent for a quick-commerce assistant.
    Two gathering subgraphs are available:
    - qa: searches store policy documents (refunds, delivery, cancellation) and the user's own order history.
    - discovery: checks the live product catalog for what's currently in stock and at what price.
      Discovery does NOT know facts about the world (recipes, dish ingredients, general knowledge) —
      it can only tell you whether a specific item is available in the store.

    Read the full conversation and decide which subgraph(s), if any, are needed to gather store-specific
    facts for the user's CURRENT question. If the question needs a general-knowledge answer (e.g. "what
    are the ingredients for X"), that will be answered directly using the model's own knowledge — dispatch
    to discovery only for the part that requires checking real store data.

    IMPORTANT: if the user asks, even implicitly, whether ANY specific named item is available, in stock,
    or carried by the store (e.g. "do you have X", "what about X", "is X on this app"), you MUST dispatch
    a discovery task for that exact item — never leave stock/availability questions unverified, even if
    the message also contains a general-knowledge part you'll answer directly.

    CRITICAL: the query you write for each dispatched subgraph must be self-contained. If the user's
    current message uses a reference like "it", "that", "the item", or omits the product name entirely
    because it was already named earlier in the conversation, resolve it to the actual specific item name
    from earlier turns before writing the query — never dispatch a vague or unresolved term.

    If no store data is needed at all, return an empty task list. Form a specific, self-contained query
    for each dispatched subgraph."""

    plan: DispatchPlan = (
        ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Conversation so far:\n{transcript}")
        ]) | get_structured_llm(DispatchPlan)
    ).invoke({"transcript": transcript})

    logger.info(f"Planner dispatching: {[(t.target, t.query) for t in plan.tasks]}")
    return {"dispatch_tasks": [t.model_dump() for t in plan.tasks]}