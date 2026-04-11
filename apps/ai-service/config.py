from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: Literal["development", "staging", "production"] = "development"

    # OpenAI
    OPENAI_API_KEY: str

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str
    NEO4J_DATABASE: str = "neo4j"

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

    # Fitbit OAuth2
    FITBIT_CLIENT_ID: str = ""
    FITBIT_SECRET: str = ""
    FITBIT_REDIRECT_URI: str = "http://localhost:3000/wearables/fitbit/callback"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "https://health.app"]

    # Models
    PRIMARY_MODEL: str = "gpt-4o"
    FAST_MODEL: str = "gpt-4o-mini"

    # Limits
    MAX_CONTEXT_TOKENS: int = 3000
    RAG_TOP_K: int = 10


settings = Settings()  # type: ignore[call-arg]
