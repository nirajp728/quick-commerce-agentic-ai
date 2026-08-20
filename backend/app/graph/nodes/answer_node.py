import logging
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_llm
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def _build_transcript(messages):
    return "\n".join(f"{'User' if m.type == 'human' else 'Assistant'}: {m.content}" for m in messages)

def answer_node(state: AgentState) -> dict:
    """
    Writes the final reply for qa/discovery-gathered facts. Only ever
    reached when no transactional subgraph (cart/refund) produced its
    own message this turn — see route_after_dispatch. The prompt itself
    still carries an explicit guard against claiming any transactional
    outcome, as defense in depth: this node has no tool access and no
    way to know whether any action actually succeeded.
    """
    logger.info("Executing Answer Node...")
    transcript = _build_transcript(state.get("messages", []))
    gathered = "\n".join(f"- {c}" for c in state.get("gathered_context", [])) or ""

    system_prompt = """You are a helpful assistant for a quick-commerce grocery platform. Answer the
    user's CURRENT (most recent) question directly and naturally, using your own general knowledge —
    the same way you would answer anyone. There is no restriction on using outside/general knowledge;
    you have it, and should use it freely for anything factual (recipes, ingredients, how-to, general
    info, etc.).

    Separately, below is some store-specific data (catalog availability, prices, policies, order
    history, or web search results) that may or may not be relevant — if it is, weave it in naturally.
    If it's empty or irrelevant to this question, ignore it entirely and just answer normally from your
    own knowledge. Never claim you lack access to general knowledge — you don't; that limitation does
    not exist.

    CRITICAL: never state or imply whether a specific item is or isn't in stock, carried, or available
    unless the gathered store data below explicitly confirms it.

    CRITICAL: you have NO ability to perform actions (refunds, cart changes, payments) and NO
    visibility into whether any transaction succeeded. NEVER claim, imply, or confirm that a refund
    was processed, a payment was made, wallet balance changed, or any transactional action completed —
    you did not perform it and cannot know its outcome. If the conversation appears to involve an
    ongoing transaction, describe only what's in the gathered store-specific data below (e.g. order
    contents, policy terms) — never invent or assume a completion status for the transaction itself.

    Do not restate anything already resolved earlier in the conversation.

    Store-specific data (optional, may be empty):
    {gathered}"""

    response = (
        ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Conversation so far:\n{transcript}")
        ]) | get_llm()
    ).invoke({"transcript": transcript, "gathered": gathered}).content

    if isinstance(response, list):
        response = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in response)

    return {"messages": [AIMessage(content=response)], "gathered_context": []}