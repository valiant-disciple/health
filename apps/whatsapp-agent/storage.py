"""Supabase Storage wrapper. We upload PDFs there and serve signed URLs."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import httpx
import structlog

from config import get_settings

log = structlog.get_logger()


def _headers() -> dict[str, str]:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.supabase_service_role_key}",
        "apikey": s.supabase_service_role_key,
    }


def _bucket_url() -> str:
    s = get_settings()
    return f"{s.supabase_url}/storage/v1"


async def upload_pdf(user_id: str, pdf_bytes: bytes, *, source_msg_sid: str | None = None) -> str:
    """Upload a PDF to the lab-reports bucket. Returns the storage path (key)."""
    s = get_settings()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"{user_id}/{today}/{uuid4().hex}.pdf"

    url = f"{_bucket_url()}/object/{s.supabase_storage_bucket}/{key}"
    headers = {
        **_headers(),
        "Content-Type": "application/pdf",
        "x-upsert": "false",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, content=pdf_bytes, headers=headers)
        if resp.status_code >= 300:
            log.error("storage.upload_failed", status=resp.status_code, body=resp.text[:200])
            raise RuntimeError(f"upload failed: {resp.status_code}")

    log.info("storage.uploaded", key=key, bytes=len(pdf_bytes))
    return key


async def signed_url(storage_key: str, *, expires_in: int = 60 * 60 * 24) -> str:
    """Generate a time-limited signed URL for a stored object. Default: 24h."""
    s = get_settings()
    url = f"{_bucket_url()}/object/sign/{s.supabase_storage_bucket}/{storage_key}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json={"expiresIn": expires_in}, headers=_headers())
        if resp.status_code >= 300:
            log.error("storage.sign_failed", status=resp.status_code, body=resp.text[:200])
            raise RuntimeError(f"sign failed: {resp.status_code}")
        data = resp.json()
    signed_path = data.get("signedURL") or data.get("signedUrl") or ""
    if signed_path.startswith("/"):
        return f"{_bucket_url()}{signed_path}"
    return f"{s.supabase_url}{signed_path}" if signed_path.startswith("/storage") else signed_path


async def download(storage_key: str) -> bytes:
    s = get_settings()
    url = f"{_bucket_url()}/object/{s.supabase_storage_bucket}/{storage_key}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.content


async def delete(storage_key: str) -> bool:
    s = get_settings()
    url = f"{_bucket_url()}/object/{s.supabase_storage_bucket}/{storage_key}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.delete(url, headers=_headers())
        return resp.status_code < 300
