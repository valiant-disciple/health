"""Centralised configuration. Loaded once at startup, immutable thereafter."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ──
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "info"
    public_base_url: str = "http://localhost:8000"

    # ── Twilio ──
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str = "whatsapp:+14155238886"

    # ── OpenAI ──
    openai_api_key: str
    orchestrator_model: str = "gpt-4o"
    extractor_model: str = "gpt-4.1-nano"
    vision_model: str = "gpt-4o"

    # ── Mistral (OCR) ──
    mistral_api_key: str = ""

    # ── Supabase ──
    supabase_url: str
    supabase_service_role_key: str
    supabase_db_url: str
    supabase_pooler_url: str = ""
    supabase_storage_bucket: str = "lab-reports"

    # ── Upstash Redis ──
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # ── App secrets ──
    phone_hash_pepper: str
    pii_encryption_key: str = ""
    internal_api_key: str = ""

    # ── Observability ──
    sentry_dsn: str = ""
    posthog_api_key: str = ""
    posthog_host: str = "https://eu.i.posthog.com"

    # ── Limits ──
    rate_limit_msg_per_min: int = 10
    rate_limit_pdfs_per_day: int = 30
    rate_limit_msg_per_day: int = 200
    max_pdf_size_mb: int = 10
    max_pdf_pages: int = 50
    daily_user_spend_cap_usd: float = 1.00
    global_daily_spend_cap_usd: float = 50.00

    # ── Behavior ──
    conversation_history_turns: int = 10
    conversation_summary_threshold: int = 30
    lab_history_days: int = 180
    prompt_version: str = "v1"

    # Convenience
    @property
    def is_prod(self) -> bool:
        return self.environment == "production"

    @property
    def db_pool_dsn(self) -> str:
        """Use pooler URL when set (transaction mode), else direct DB URL."""
        return self.supabase_pooler_url or self.supabase_db_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
