"""Upstash Redis REST client. Used for ephemeral fast-path state.

We talk over HTTPS REST instead of the Redis wire protocol because:
  - Upstash REST works from anywhere (no VPC, no TCP egress).
  - Stateless: each call is independent — no connection pool to manage.
  - Latency overhead is ~5-15ms which is fine for our use case.

Currently used for: (nothing critical — kept available as a fast cache).
Rate limiting is done in Postgres (see guardrails/ratelimit.py).
"""
from __future__ import annotations

import httpx
import structlog

from config import get_settings

log = structlog.get_logger()


class UpstashRedis:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(5.0, connect=2.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _cmd(self, *args: str | int) -> dict:
        client = await self._get_client()
        body = [str(a) for a in args]
        try:
            resp = await client.post("/", json=body)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            log.warning("redis.command_failed", cmd=args[0] if args else None, error=str(e))
            return {"error": str(e)}

    # Public helpers
    async def get(self, key: str) -> str | None:
        r = await self._cmd("GET", key)
        return r.get("result")

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        args: list[str | int] = ["SET", key, value]
        if ex is not None:
            args += ["EX", ex]
        r = await self._cmd(*args)
        return r.get("result") == "OK"

    async def incr(self, key: str) -> int:
        r = await self._cmd("INCR", key)
        return int(r.get("result", 0))

    async def expire(self, key: str, seconds: int) -> bool:
        r = await self._cmd("EXPIRE", key, seconds)
        return r.get("result") == 1

    async def delete(self, *keys: str) -> int:
        r = await self._cmd("DEL", *keys)
        return int(r.get("result", 0))

    async def ping(self) -> bool:
        r = await self._cmd("PING")
        return r.get("result") == "PONG"


_redis: UpstashRedis | None = None


def get_redis() -> UpstashRedis:
    global _redis
    if _redis is None:
        s = get_settings()
        if not s.upstash_redis_rest_url or not s.upstash_redis_rest_token:
            raise RuntimeError("Upstash Redis credentials not configured")
        _redis = UpstashRedis(s.upstash_redis_rest_url, s.upstash_redis_rest_token)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
