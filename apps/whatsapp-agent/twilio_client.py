"""Twilio WhatsApp client — both inbound (signature verify) and outbound (send)."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from twilio.request_validator import RequestValidator

from config import get_settings

log = structlog.get_logger()

_validator: RequestValidator | None = None
_http: httpx.AsyncClient | None = None


def _get_validator() -> RequestValidator:
    global _validator
    if _validator is None:
        _validator = RequestValidator(get_settings().twilio_auth_token)
    return _validator


async def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        s = get_settings()
        _http = httpx.AsyncClient(
            base_url=f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}",
            auth=(s.twilio_account_sid, s.twilio_auth_token),
            timeout=httpx.Timeout(15.0, connect=3.0),
        )
    return _http


async def close_http() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def verify_signature(url: str, params: dict[str, str], signature: str) -> bool:
    """Verify an incoming webhook came from Twilio.

    `url` should be the full external-facing URL (PUBLIC_BASE_URL + path + query),
    NOT the URL FastAPI sees internally (which may be missing https://).
    """
    return _get_validator().validate(url, params, signature)


async def download_media(media_url: str) -> bytes:
    """Download media from Twilio's CDN. Requires basic auth with Twilio creds."""
    s = get_settings()
    async with httpx.AsyncClient(
        auth=(s.twilio_account_sid, s.twilio_auth_token),
        timeout=httpx.Timeout(30.0, connect=5.0),
        follow_redirects=True,
    ) as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
        return resp.content


async def send_whatsapp(
    to: str,
    body: str,
    media_url: str | None = None,
    *,
    retries: int = 2,
) -> dict[str, Any]:
    """Send a WhatsApp message via Twilio REST API.

    Returns the Twilio response payload. Retries on transient errors.
    """
    s = get_settings()
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"

    data = {
        "From": s.twilio_whatsapp_from,
        "To": to,
        "Body": body[:1600],  # WhatsApp soft limit
    }
    if media_url:
        data["MediaUrl"] = media_url

    http = await _get_http()
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await http.post("/Messages.json", data=data)
            if resp.status_code >= 500:
                raise RuntimeError(f"twilio 5xx: {resp.status_code} {resp.text[:200]}")
            if resp.status_code == 429:
                raise RuntimeError("twilio rate limit")
            if resp.status_code >= 400:
                # Client error — don't retry
                log.error(
                    "twilio.send_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                    to_hash=hash(to),
                )
                return {"error": resp.text, "status": resp.status_code}
            payload = resp.json()
            log.info("twilio.sent", sid=payload.get("sid"), to_hash=hash(to))
            return payload
        except (httpx.HTTPError, RuntimeError) as e:
            last_err = e
            if attempt < retries:
                await asyncio.sleep(0.5 * (2**attempt))
            continue

    log.error("twilio.send_exhausted", error=str(last_err))
    return {"error": str(last_err) if last_err else "unknown"}


async def send_text(to: str, body: str) -> dict[str, Any]:
    return await send_whatsapp(to, body)


def chunk_for_whatsapp(text: str, max_len: int = 1500) -> list[str]:
    """Split a long message into WhatsApp-sized chunks at sentence boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    cur = ""
    for sentence in text.replace("\n", " \n").split(". "):
        addition = sentence + ". " if not sentence.endswith("\n") else sentence
        if len(cur) + len(addition) > max_len and cur:
            chunks.append(cur.rstrip())
            cur = addition
        else:
            cur += addition
    if cur.strip():
        chunks.append(cur.rstrip())
    return chunks
