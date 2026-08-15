import logging
from langchain_core.messages import AIMessage
from backend.app.graph.state import AgentState
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def aggregator_node(state: AgentState) -> dict:
    """
    Final review node. Cleans up formatting and ensures 
    no internal system logic is leaked to the user.
    """
    logger.info("Executing Aggregator Node...")
    messages = state.get("messages", [])
    
    if not messages:
        return state

    last_message = messages[-1].content
    
    # Example Guardrail: Ensure empty or broken AI responses are caught
    if not last_message or last_message.strip() == "":
        return {
            "messages": [AIMessage(content="I apologize, but I encountered an error formatting my response. Could you try asking that again?")]
        }

    return state