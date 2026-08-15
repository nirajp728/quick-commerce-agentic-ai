import logging
from langchain_core.messages import RemoveMessage
from langchain_core.prompts import ChatPromptTemplate
from backend.app.graph.state import AgentState
from backend.app.utils.llm_factory import get_llm
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

MAX_RAW_MESSAGES = 8  # keep this many recent messages verbatim; fold the rest into a summary

def context_compressor_node(state: AgentState) -> dict:
    """Runs before the router. Once history grows past a threshold, folds
    older messages into a running summary and drops them from state via
    RemoveMessage, so nodes reading messages[-1] aren't working off an
    ever-growing, never-summarized history."""
    messages = state.get("messages", [])
    if len(messages) <= MAX_RAW_MESSAGES:
        return {}

    to_summarize = messages[:-MAX_RAW_MESSAGES]
    existing_summary = state.get("conversation_summary") or "(none yet)"

    prompt = ChatPromptTemplate.from_messages([
        ("system", "Update the running conversation summary with the new messages below. "
                   "Keep it to 2-4 sentences: unresolved topics, stated preferences, anything "
                   "likely to be referenced again.\n\nExisting summary: {summary}"),
        ("human", "New messages to fold in:\n{new_messages}")
    ])
    new_messages_text = "\n".join(f"{m.type}: {m.content}" for m in to_summarize)
    updated_summary = (prompt | get_llm()).invoke({
        "summary": existing_summary,
        "new_messages": new_messages_text
    }).content

    logger.info("Context compressor: folded %d messages into summary.", len(to_summarize))

    return {
        "conversation_summary": updated_summary,
        "messages": [RemoveMessage(id=m.id) for m in to_summarize if m.id],
    }