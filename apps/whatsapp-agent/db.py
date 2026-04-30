"""Postgres connection pool + query helpers.

We use asyncpg directly against the Supabase Postgres. This keeps us framework-
agnostic and gives us prepared-statement performance on the hot path. The
Supabase Python SDK is fine for storage operations, but for writes inside the
webhook+worker, asyncpg is faster and gives us proper connection pooling.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from config import get_settings

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        # Supabase's pooler runs in transaction mode → prepared statements
        # bound to a connection don't survive between transactions. Setting
        # statement_cache_size=0 disables asyncpg's auto-caching so each query
        # is parsed fresh. Slight overhead, no compatibility headaches.
        _pool = await asyncpg.create_pool(
            dsn=settings.db_pool_dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
            init=_init_connection,
            statement_cache_size=0,
        )
        log.info("db.pool_created", min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSONB codec to use Python json directly."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() first")
    return _pool


@asynccontextmanager
async def transaction():
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            yield conn


# ── Convenience queries ───────────────────────────────────────────────────


async def fetch_one(query: str, *args) -> dict[str, Any] | None:
    async with get_pool().acquire() as conn:
        rec = await conn.fetchrow(query, *args)
        return dict(rec) if rec else None


async def fetch_all(query: str, *args) -> list[dict[str, Any]]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]


async def execute(query: str, *args) -> str:
    async with get_pool().acquire() as conn:
        return await conn.execute(query, *args)


async def fetch_val(query: str, *args) -> Any:
    async with get_pool().acquire() as conn:
        return await conn.fetchval(query, *args)


# ── User helpers ──────────────────────────────────────────────────────────


async def get_or_create_user(phone_hash: str, phone_encrypted: bytes) -> dict[str, Any]:
    """Find existing user by phone_hash or create new."""
    user = await fetch_one(
        "SELECT * FROM users WHERE phone_hash = $1 AND deleted_at IS NULL",
        phone_hash,
    )
    if user:
        # Reset daily counters if needed
        await execute("SELECT reset_daily_counters_if_needed($1)", user["id"])
        return user

    async with transaction() as conn:
        rec = await conn.fetchrow(
            """
            INSERT INTO users (phone_hash, phone_encrypted)
            VALUES ($1, $2)
            ON CONFLICT (phone_hash) DO UPDATE SET phone_hash = EXCLUDED.phone_hash
            RETURNING *
            """,
            phone_hash,
            phone_encrypted,
        )
        return dict(rec)


async def increment_user_message_count(user_id: UUID) -> None:
    await execute(
        """
        UPDATE users
           SET total_messages = total_messages + 1,
               daily_message_count = daily_message_count + 1
         WHERE id = $1
        """,
        user_id,
    )


async def increment_user_pdf_count(user_id: UUID) -> None:
    await execute(
        """
        UPDATE users
           SET total_reports = total_reports + 1,
               daily_pdf_count = daily_pdf_count + 1
         WHERE id = $1
        """,
        user_id,
    )


async def add_user_spend(user_id: UUID, usd: float) -> None:
    await execute(
        """
        UPDATE users
           SET daily_spend_usd = daily_spend_usd + $2,
               total_spend_usd = total_spend_usd + $2
         WHERE id = $1
        """,
        user_id,
        usd,
    )


# ── Idempotency ───────────────────────────────────────────────────────────


async def is_message_processed(twilio_sid: str) -> bool:
    """Returns True if we've already processed this MessageSid."""
    rec = await fetch_one(
        "INSERT INTO processed_messages (twilio_sid) VALUES ($1) "
        "ON CONFLICT (twilio_sid) DO NOTHING RETURNING twilio_sid",
        twilio_sid,
    )
    return rec is None  # if INSERT returned None → conflict → already processed


# ── Audit ─────────────────────────────────────────────────────────────────


async def audit(
    user_id: UUID | None,
    action: str,
    metadata: dict | None = None,
    ip_hash: str | None = None,
) -> None:
    await execute(
        "INSERT INTO audit_log (user_id, action, metadata, ip_hash) VALUES ($1, $2, $3, $4)",
        user_id,
        action,
        metadata or {},
        ip_hash,
    )
