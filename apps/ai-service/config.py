from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: Literal["development", "staging", "production"] = "development"

    # Anthropic
    ANTHROPIC_API_KEY: str

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str

    # Qdrant
    QDRANT_URL: str
    QDRANT_API_KEY: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Langfuse
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Spike API (lab OCR)
    SPIKE_API_KEY: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "https://health.app"]

    # Models
    PRIMARY_MODEL: str = "claude-sonnet-4-6"
    FAST_MODEL: str = "claude-haiku-4-5-20251001"

    # Limits
    MAX_CONTEXT_TOKENS: int = 3000
    RAG_TOP_K: int = 10


settings = Settings()  # type: ignore[call-arg]
