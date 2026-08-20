import json
import logging
from langchain_core.tools import tool
from tavily import TavilyClient
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

@tool
def web_search(query: str) -> str:
    """
    Searches the live web for general knowledge not available in the
    store's own policy/product data. Used by the QA subgraph's CRAG loop
    when local retrieval is graded ambiguous or incorrect.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not set — web search unavailable.")
        return json.dumps({"context": "Web search is not configured."})

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        results = client.search(query, max_results=3)
        context = "\n".join(r.get("content", "") for r in results.get("results", []))
        return json.dumps({"context": context or "No web results found."})
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return json.dumps({"context": "Web search failed."})