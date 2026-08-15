import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from backend.app.config import settings

logger = logging.getLogger(settings.APP_NAME)

def _build_primary():
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in the environment variables.")
    return ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.1,
        max_retries=3,
    )

def _build_fallbacks():
    fallbacks = []
    if settings.GROQ_API_KEY:
        fallbacks.append(ChatGroq(model="llama-3.1-70b-versatile", groq_api_key=settings.GROQ_API_KEY, temperature=0.1))
    if settings.OPENAI_API_KEY:
        fallbacks.append(ChatOpenAI(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY, temperature=0.1))
    return fallbacks

def get_llm():
    """Plain chat model (Gemini) with Groq/OpenAI fallbacks. Use this for
    direct generation calls (no structured output)."""
    primary = _build_primary()
    fallbacks = _build_fallbacks()
    return primary.with_fallbacks(fallbacks) if fallbacks else primary

def get_structured_llm(schema):
    """Returns a structured-output-bound model with fallbacks. Fallbacks
    must be applied AFTER .with_structured_output() per-model — applying
    them before breaks .with_structured_output() entirely, since
    RunnableWithFallbacks isn't a BaseChatModel."""
    primary = _build_primary().with_structured_output(schema)
    fallbacks = [m.with_structured_output(schema) for m in _build_fallbacks()]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary