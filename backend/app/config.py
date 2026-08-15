from functools import lru_cache
from pathlib import Path
from typing import List, Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"  # backend/.env, regardless of cwd


class Settings(BaseSettings):
    """
    Application Settings for the Quick-Commerce Agentic AI Platform.
    Loads and validates configuration from environment variables or a .env file.
    """

    # ------------------------------------------------------------------
    # Application & Environment Settings
    # ------------------------------------------------------------------
    APP_NAME: str = "QuickCommerce-Agentic-AI"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    CHAT_THREAD_TTL_HOURS: int = 24

    # ------------------------------------------------------------------
    # FastAPI Server & CORS Settings
    # ------------------------------------------------------------------
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    # ------------------------------------------------------------------
    # MongoDB Database & Vector Search
    # ------------------------------------------------------------------
    MONGODB_URI: str = Field(default="mongodb://localhost:27017")
    MONGODB_DB_NAME: str = "quick_commerce_db"
    POLICY_VECTOR_INDEX_NAME: str = "policy_vector_index"

    # ------------------------------------------------------------------
    # LLM Providers & Embeddings
    # ------------------------------------------------------------------
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # ------------------------------------------------------------------
    # Observability & Tracing (LangSmith)
    # ------------------------------------------------------------------
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "quick-commerce-agent"

    # ------------------------------------------------------------------
    # Messaging Gateways (Twilio WhatsApp)
    # ------------------------------------------------------------------
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_NUMBER: str = "whatsapp:+14155238886"

    # ------------------------------------------------------------------
    # Cloud Media Storage (Cloudinary)
    # ------------------------------------------------------------------
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # ------------------------------------------------------------------
    # Admin WebSocket Auth
    # ------------------------------------------------------------------
    ADMIN_WS_TOKEN: str = ""

    # Configuration Model Metadata
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @model_validator(mode="after")
    def _lock_down_production(self) -> "Settings":
        """
        Production must never inherit local dev defaults just because DEBUG
        or CORS_ORIGINS weren't explicitly set. DEBUG is forced off, and a
        wildcard CORS origin is rejected outright rather than silently
        allowed, since that combination has caused real security incidents
        in other projects.
        """
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                self.DEBUG = False
            if self.CORS_ORIGINS == ["*"]:
                raise ValueError(
                    "CORS_ORIGINS must be set to explicit allowed origins when ENVIRONMENT=production "
                    "(wildcard '*' is not permitted in production)."
                )
        return self

    @property
    def is_production(self) -> bool:
        """Utility property to check if current environment is production."""
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the application settings to avoid
    re-reading environment variables or .env files on every request.
    """
    return Settings()


# Global settings singleton instance
settings = get_settings()