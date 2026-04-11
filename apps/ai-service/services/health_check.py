"""
Detailed health check — probes each external dependency.

Used by GET /health/detailed. Each probe returns:
  {"status": "ok"|"degraded"|"unavailable", "latency_ms": float, "detail": str}

The overall status is:
  ok         — all probes pass
  degraded   — at least one probe is degraded but the service can still function
  unavailable — a critical dependency is down
"""
from __future__ import annotations

import asyncio
import time
import structlog

log = structlog.get_logger()


async def _probe_supabase() -> dict:
    start = time.monotonic()
    try:
        from services.db import get_supabase
        db = await get_supabase()
        # Simple lightweight query
        await db.table("health_events").select("id").limit(1).execute()
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {
            "status": "unavailable",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "detail": str(e)[:120],
        }


async def _probe_qdrant() -> dict:
    start = time.monotonic()
    try:
        from config import settings
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
        await client.get_collections()
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {
            "status": "degraded",  # Qdrant down = RAG unavailable, but chat still works
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "detail": str(e)[:120],
        }


async def _probe_neo4j() -> dict:
    start = time.monotonic()
    try:
        from services.memory import _graphiti
        if _graphiti is None:
            return {"status": "degraded", "latency_ms": 0, "detail": "Graphiti not initialised"}
        # Graphiti doesn't expose a ping — use driver directly
        from config import settings
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {
            "status": "degraded",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "detail": str(e)[:120],
        }


async def _probe_openai() -> dict:
    """Lightweight check — just verify the API key is accepted."""
    start = time.monotonic()
    try:
        from openai import AsyncOpenAI
        from config import settings
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # models.list is the cheapest call
        await client.models.list()
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {
            "status": "unavailable",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "detail": str(e)[:120],
        }


async def run_health_checks() -> dict:
    """
    Run all probes concurrently. Returns a dict suitable for /health/detailed.
    """
    supabase, qdrant, neo4j, openai = await asyncio.gather(
        _probe_supabase(),
        _probe_qdrant(),
        _probe_neo4j(),
        _probe_openai(),
        return_exceptions=True,
    )

    # Normalise any unhandled exceptions from gather
    def _normalise(result):
        if isinstance(result, Exception):
            return {"status": "unavailable", "detail": str(result)[:120]}
        return result

    probes = {
        "supabase": _normalise(supabase),
        "qdrant":   _normalise(qdrant),
        "neo4j":    _normalise(neo4j),
        "openai":   _normalise(openai),
    }

    # Determine overall status
    statuses = {p["status"] for p in probes.values()}
    if "unavailable" in statuses:
        overall = "unavailable"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "probes": probes}
