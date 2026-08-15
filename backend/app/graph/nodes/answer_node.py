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
    """Writes the final reply, always using the model's own general
    knowledge as the default source of truth, layering store-specific
    gathered facts on top only where relevant."""
    logger.info("Executing Answer Node...")
    transcript = _build_transcript(state.get("messages", []))
    gathered = "\n".join(f"- {c}" for c in state.get("gathered_context", [])) or ""

    system_prompt = """You are a helpful assistant for a quick-commerce grocery platform. Answer the
    user's CURRENT (most recent) question directly and naturally, using your own general knowledge —
    the same way you would answer anyone. There is no restriction on using outside/general knowledge;
    you have it, and should use it freely for anything factual (recipes, ingredients, how-to, general
    info, etc.).

    Separately, below is some store-specific data (catalog availability, prices, policies, order
    history) that may or may not be relevant — if it is, weave it in naturally (e.g. "you'll need X,
    Y, Z; we currently stock X and Y"). If it's empty or irrelevant to this question, ignore it
    entirely and just answer normally from your own knowledge. Never claim you lack access to general
    knowledge — you don't; that limitation does not exist.

    CRITICAL: never state or imply whether a specific item is or isn't in stock, carried, or available
    unless the gathered store data below explicitly confirms it with a real match. If the gathered data
    shows no match was found, or there's no gathered data at all, say plainly that you couldn't confirm
    it or would need to check — do not phrase an absence of data as a confident "not in stock."

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