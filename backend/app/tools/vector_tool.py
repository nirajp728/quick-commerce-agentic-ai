import json
import logging
from typing import Optional
from sentence_transformers import SentenceTransformer
from langchain_core.tools import tool

from backend.app.config import settings
from backend.app.db.mongo_client import get_sync_policies_collection

logger = logging.getLogger(settings.APP_NAME)

_embedder: Optional[SentenceTransformer] = None

def _get_embedder() -> SentenceTransformer:
    """Lazily loads the embedding model once per process. Must match the
    model used in seed_db.py (all-MiniLM-L6-v2) so query vectors and
    stored document vectors live in the same embedding space."""
    global _embedder
    if _embedder is None:
        logger.info("Loading sentence-transformers model for query embedding...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder

@tool
def search_store_policies(query: str) -> str:
    """
    Performs a semantic vector search against the store's policy documents.
    Use this to find rules about delivery times, refunds, and cancellations.
    """
    logger.info(f"Executing Vector Search for: '{query}'")

    query_vector = _get_embedder().encode(query).tolist()
    collection = get_sync_policies_collection()

    pipeline = [
        {
            "$vectorSearch": {
                "index": settings.POLICY_VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 50,
                "limit": 3,
            }
        },
        {
            "$project": {
                "_id": 0,
                "title": 1,
                "content": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    try:
        results = list(collection.aggregate(pipeline))
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return json.dumps({"context": "Policy search is temporarily unavailable."})

    if not results:
        return json.dumps({"context": "No relevant policy found for this query."})

    context = "\n\n".join(f"{r['title']}: {r['content']}" for r in results)
    return json.dumps({"context": context})