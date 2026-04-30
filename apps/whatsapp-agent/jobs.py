"""Postgres-backed message queue.

Why not pgmq / Inngest / Redis Streams? Simplicity. At MVP scale we have:
  - one worker process
  - sub-100 messages per minute
  - no fanout, no scheduling, no complex DAGs

A `message_queue` table polled with FOR UPDATE SKIP LOCKED gives us:
  - durability (rows survive crashes)
  - automatic retry-on-stuck (visible_after)
  - dead letter via attempts >= max_attempts
  - easy debugging (just SELECT)

Swap to pgmq/Inngest later when scale or workflow complexity justifies it.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog

from db import execute, fetch_one, get_pool

log = structlog.get_logger()


async def enqueue(
    user_id: UUID | None,
    payload: dict[str, Any],
    *,
    delay_seconds: int = 0,
) -> UUID:
    """Push a job onto the queue. Returns its id."""
    visible_after_clause = "now() + ($3 || ' seconds')::interval" if delay_seconds else "now()"
    sql = f"""
        INSERT INTO message_queue (user_id, payload, visible_after)
        VALUES ($1, $2, {visible_after_clause})
        RETURNING id
    """
    args = [user_id, payload]
    if delay_seconds:
        args.append(str(delay_seconds))
    rec = await fetch_one(sql, *args)
    log.info("queue.enqueued", id=str(rec["id"]) if rec else None, type=payload.get("type"))
    return rec["id"]


async def claim_next(worker_id: str = "default") -> dict | None:
    """Atomically claim the next pending job. Returns None if queue empty."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE message_queue
                   SET status = 'processing',
                       processing_started_at = now(),
                       attempts = attempts + 1
                 WHERE id = (
                   SELECT id FROM message_queue
                    WHERE status = 'pending'
                      AND visible_after <= now()
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                 )
                RETURNING id, user_id, payload, attempts, max_attempts, created_at
                """,
            )
            return dict(row) if row else None


async def mark_done(job_id: UUID) -> None:
    await execute(
        "UPDATE message_queue SET status='done', processed_at=now() WHERE id = $1",
        job_id,
    )


async def mark_failed(job_id: UUID, error: str, *, retry_in_seconds: int | None = None) -> None:
    """Mark a job failed. If retry_in_seconds set and attempts < max, requeue with delay."""
    rec = await fetch_one(
        "SELECT attempts, max_attempts FROM message_queue WHERE id = $1",
        job_id,
    )
    if not rec:
        return
    if retry_in_seconds is not None and rec["attempts"] < rec["max_attempts"]:
        await execute(
            """
            UPDATE message_queue
               SET status = 'pending',
                   visible_after = now() + ($2 || ' seconds')::interval,
                   error = $3
             WHERE id = $1
            """,
            job_id, str(retry_in_seconds), error[:1000],
        )
        log.info("queue.retrying", id=str(job_id), in_s=retry_in_seconds)
    else:
        await execute(
            "UPDATE message_queue SET status='failed', error=$2 WHERE id=$1",
            job_id, error[:1000],
        )
        log.warning("queue.dead_lettered", id=str(job_id))


async def reclaim_stuck(*, stuck_seconds: int = 300) -> int:
    """Reset jobs that have been 'processing' too long (worker crashed)."""
    res = await execute(
        f"""
        UPDATE message_queue
           SET status = 'pending', visible_after = now()
         WHERE status = 'processing'
           AND processing_started_at < now() - interval '{stuck_seconds} seconds'
        """,
    )
    return int(res.split()[-1]) if res.startswith("UPDATE") else 0


async def stats() -> dict[str, int]:
    rec = await fetch_one(
        """
        SELECT
          count(*) FILTER (WHERE status='pending')    AS pending,
          count(*) FILTER (WHERE status='processing') AS processing,
          count(*) FILTER (WHERE status='done')       AS done,
          count(*) FILTER (WHERE status='failed')     AS failed
          FROM message_queue
        """,
    )
    return {k: int(v or 0) for k, v in (rec or {}).items()}
