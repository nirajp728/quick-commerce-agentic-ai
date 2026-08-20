import logging
from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_structured_llm
from backend.app.tools.db_tools import check_inventory
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)
MAX_CLARIFICATION_ATTEMPTS = 4

class ClarityCheck(BaseModel):
    intent: Literal["clear", "unclear", "handoff", "refuse"] = Field(
        description="'clear' if the current question can be acted on. 'unclear' if more info is needed. "
                    "'handoff' if explicit human request or clearly angry tone. 'refuse' if dangerous/illegal."
    )
    sentiment_score: float = Field(description="-1.0 (furious) to 1.0 (happy), 0.0 neutral.")
    needs_catalog_lookup: bool = Field(
        default=False,
        description="True ONLY when the user explicitly asks for a general category with no specific "
                    "product named (e.g. 'add some chips', 'any chip is fine'). False if specific "
                    "products are already named, even multiple at once."
    )
    catalog_lookup_term: Optional[str] = Field(
        default=None, description="If needs_catalog_lookup is True, ONLY the vague category term, e.g. 'chips'."
    )
    clarifying_question: Optional[str] = Field(default=None)

def _transcript(messages) -> str:
    return "\n".join(f"{'User' if m.type == 'human' else 'Assistant'}: {m.content}" for m in messages)

SCOPE_PROMPT = """You are the clarification gate for a Quick-Commerce grocery assistant.
This platform can: modify a shopping cart, process refunds, answer store policy/order-history
questions, check product availability, and answer general questions using its own knowledge plus
optional web search. It cannot: place real-world non-grocery orders, access unrelated external
services, or do anything unsafe/illegal.

Judge whether the user's CURRENT message is clear enough for the system to act on — read the full
transcript for general context, but you do not need to track whether this continues, answers, or
abandons any specific earlier topic. That routing decision belongs to a separate planning step
downstream; your only job is: is this message coherent and in-scope, or do you genuinely need more
information before anything useful can be done with it at all?

IMPORTANT: set needs_catalog_lookup=True ONLY when the user explicitly asks for a general category
with no specific product named (e.g. "add some chips", "any chip is fine"). Do NOT set this for
messages that already name specific products, even multiple at once. When True, catalog_lookup_term
must be ONLY the vague category word, never a multi-item sentence."""

def _build_catalog_question(term: str) -> str:
    result = json.loads(check_inventory.invoke({"query": term, "limit": 5}))
    if result.get("status") != "success" or not result.get("items"):
        return f"We don't seem to have anything matching \"{term}\" in stock right now — could you try a different item?"
    names = [item["name"] for item in result["items"]]
    return f"We have: {', '.join(names)}. Which one would you like?"

def clarification_node(state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages:
        return {"clarification_attempts": 0}

    transcript = _transcript(messages)
    prompt = ChatPromptTemplate.from_messages([("system", SCOPE_PROMPT), ("human", "Conversation:\n{transcript}")])
    result: ClarityCheck = (prompt | get_structured_llm(ClarityCheck)).invoke({"transcript": transcript})

    if result.intent == "refuse":
        return {"current_intent": "refuse", "is_handed_off": False,
                "messages": [AIMessage(content="I can't help with that.")]}

    if result.sentiment_score <= -0.5 or result.intent == "handoff":
        return {"current_intent": "handoff", "is_handed_off": True, "sentiment_score": result.sentiment_score}

    if result.intent == "clear":
        return {"clarification_attempts": 0, "sentiment_score": result.sentiment_score}

    attempts = state.get("clarification_attempts", 0) + 1
    if attempts >= MAX_CLARIFICATION_ATTEMPTS:
        return {"current_intent": "handoff", "is_handed_off": True, "clarification_attempts": attempts,
                "messages": [AIMessage(content="I'm having trouble understanding — let me connect you with a human agent.")]}

    if result.needs_catalog_lookup and result.catalog_lookup_term:
        question = _build_catalog_question(result.catalog_lookup_term)
    else:
        question = result.clarifying_question or "Could you clarify what you need?"

    return {
        "clarification_attempts": attempts,
        "sentiment_score": result.sentiment_score,
        "messages": [AIMessage(content=question)],
    }

def route_after_clarification(state: AgentState) -> str:
    if state.get("is_handed_off"):
        return "handoff"
    if state.get("current_intent") == "refuse":
        return "end_turn"
    if state.get("clarification_attempts", 0) > 0:
        return "end_turn"
    return "planner"