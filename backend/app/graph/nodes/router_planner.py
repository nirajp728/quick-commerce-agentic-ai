import logging
from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_structured_llm
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

class RouterOutput(BaseModel):
    """
    Forces the LLM to output a strict JSON structure for routing,
    preventing arbitrary string responses that break graph edges.
    """
    intent: Literal["cart", "refund", "qa", "discovery", "handoff", "clarify"] = Field(
        description="The primary intent of the user's latest message, read in context of the full conversation."
    )
    sentiment_score: float = Field(
        description="A continuous score from -1.0 (extremely angry/frustrated) to 1.0 (extremely positive/happy)."
    )
    has_enough_info: bool = Field(
        description="True if the conversation so far gives you enough information to act on this intent right now. "
                    "False if you genuinely need to ask the user something before you can proceed."
    )
    clarifying_question: Optional[str] = Field(
        default=None,
        description="Required when has_enough_info is False. A short, specific question that would get you the missing information."
    )

def _build_transcript(messages) -> str:
    """Renders the full thread history as a simple role-labeled transcript,
    so the router judges intent/sufficiency against everything said so far,
    not just the latest message in isolation."""
    lines = []
    for m in messages:
        role = "User" if m.type == "human" else "Assistant"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)

def router_node(state: AgentState) -> dict:
    """
    Reads the full conversation so far, determines intent, sentiment, and
    whether there's enough context to act — asking a clarifying question
    instead if not.
    """
    logger.info("Executing Router Node...")

    messages = state.get("messages", [])
    if not messages:
        return {"current_intent": "clarify", "sentiment_score": 0.0}

    transcript = _build_transcript(messages)

    system_prompt = """You are the master routing agent for a Quick-Commerce grocery platform.
    Read the full conversation below and classify the user's current intent.

    Available Intents:
    - cart: User wants to ADD, remove, or modify items already in their shopping cart. This is NOT for
      asking whether an item exists or is in stock — that's discovery, even if phrased like "do you have X".
    - refund: User has an issue with a past order, wants a refund, or complains about a damaged/missing item.
    - qa: User is asking about store policies, delivery times, operations, general FAQs, or wants to look up their past order history / order IDs (this is different from wanting a refund).
    - discovery: User wants product recommendations, recipe ingredients, budget-based suggestions, or is
      asking whether a specific item is available/in stock (e.g. "do you have X", "is X available").
    - handoff: User explicitly demands to speak to a human, customer support, or an agent.
    - clarify: The request is too vague, contradictory, or completely unrelated to quick-commerce.

    Judge has_enough_info honestly: if the conversation gives you what you need to act (even a short,
    clear request like "add 2 milk"), say True. Only say False if something essential is genuinely missing
    or ambiguous and you'd have to guess.

    Note: even if the conversation history shows an unrelated task in progress (e.g. a pending refund),
    classify based on what the user's LATEST message is actually asking for — don't force it into the
    ongoing topic if it's clearly a different request.

    Sentiment Analysis:
    Score the user's emotional tone from -1.0 (furious/abusive) to 1.0 (happy/polite). 0.0 is neutral.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Conversation so far:\n{transcript}")
    ])

    structured_llm = get_structured_llm(RouterOutput)
    chain = prompt | structured_llm

    try:
        result: RouterOutput = chain.invoke({"transcript": transcript})
        logger.info(f"Router Result: Intent={result.intent}, HasEnoughInfo={result.has_enough_info}, Sentiment={result.sentiment_score}")

        final_intent = result.intent
        is_handed_off = state.get("is_handed_off", False)
        new_messages = []

        # Sentiment/explicit handoff always takes priority over everything else
        if result.sentiment_score <= -0.5 or result.intent == "handoff":
            logger.warning("Sentiment threshold breached or explicit handoff requested. Triggering HITL.")
            final_intent = "handoff"
            is_handed_off = True
        elif not result.has_enough_info:
            logger.info("Router: not enough info yet. Asking a clarifying question.")
            final_intent = "clarify"
            new_messages.append(AIMessage(content=result.clarifying_question or "Could you tell me a bit more about what you need?"))

        updates = {
            "current_intent": final_intent,
            "sentiment_score": result.sentiment_score,
            "is_handed_off": is_handed_off,
        }
        if new_messages:
            updates["messages"] = new_messages
        return updates

    except Exception as e:
        logger.error(f"Router Node Error: {e}")
        return {
            "current_intent": "clarify",
            "sentiment_score": 0.0,
            "messages": [AIMessage(content="I'm having trouble understanding right now. Could you rephrase that?")]
        }