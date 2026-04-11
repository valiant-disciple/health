"""
Wearable ingestion router.
  POST /wearables/apple-health/upload   — parse Apple Health export (XML or zip)
  GET  /wearables/fitbit/connect        — start Fitbit OAuth PKCE flow
  POST /wearables/fitbit/callback       — exchange code for tokens
  POST /wearables/fitbit/sync           — pull latest data from Fitbit
  GET  /wearables/status                — list connected wearables for the user
  DELETE /wearables/{provider}          — disconnect a wearable
"""
from __future__ import annotations

import asyncio
import json
import secrets
from datetime import date, datetime, timezone, timedelta

import structlog
from fastapi import APIRouter, Header, HTTPException, UploadFile, File
from pydantic import BaseModel

from services.db import get_supabase
from services.vector import upsert_health_event

log = structlog.get_logger()
router = APIRouter()

SUPPORTED_PROVIDERS = {"fitbit", "apple_health"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


# ─── Apple Health upload ─────────────────────────────────────────────────────

@router.post("/apple-health/upload")
async def upload_apple_health(
    file: UploadFile = File(...),
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """
    Accept export.zip or export.xml from iPhone Health app.
    Parses, deduplicates, and stores into health_events + Qdrant.
    Returns count of new events inserted.
    """
    if not file.filename or not (
        file.filename.endswith(".xml") or file.filename.endswith(".zip")
    ):
        raise HTTPException(400, "File must be export.xml or export.zip")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit")

    log.info("apple_health.upload_received", user_id=x_user_id, size_kb=len(content) // 1024)

    # Run parse in background — can be slow for large exports
    asyncio.create_task(_process_apple_upload(x_user_id, content))

    # Upsert/update connection record
    db = await get_supabase()
    await db.table("wearable_connections").upsert({
        "user_id":  x_user_id,
        "provider": "apple_health",
        "status":   "connected",
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,provider").execute()

    return {"status": "processing", "message": "Apple Health data is being imported in the background."}


async def _process_apple_upload(user_id: str, file_bytes: bytes):
    from services.wearables.apple_health import parse_apple_health_export
    try:
        events = parse_apple_health_export(file_bytes, user_id)
        inserted = await _bulk_insert_events(user_id, events)
        asyncio.create_task(_store_wearable_episodes(user_id, events))
        db = await get_supabase()
        await db.table("wearable_connections").update({
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "metadata": json.dumps({"last_import_count": inserted}),
        }).eq("user_id", user_id).eq("provider", "apple_health").execute()
        log.info("apple_health.import_done", user_id=user_id, inserted=inserted)
    except Exception as e:
        log.error("apple_health.import_failed", user_id=user_id, error=str(e), exc_info=True)
        db = await get_supabase()
        await db.table("wearable_connections").update({
            "status":   "error",
            "metadata": json.dumps({"error": str(e)}),
        }).eq("user_id", user_id).eq("provider", "apple_health").execute()


# ─── Fitbit OAuth ─────────────────────────────────────────────────────────────

@router.get("/fitbit/connect")
async def fitbit_connect(
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """Return the Fitbit authorization URL + PKCE state for the frontend to redirect to."""
    from services.wearables.fitbit import generate_pkce_pair, build_auth_url, get_fitbit_credentials
    # Validate Fitbit credentials are configured before touching the DB
    try:
        get_fitbit_credentials()
    except ValueError as e:
        raise HTTPException(503, str(e))

    code_verifier, code_challenge = generate_pkce_pair()
    state = f"{x_user_id}:{secrets.token_urlsafe(16)}"

    # Store verifier in wearable_connections temporarily (keyed by state)
    db = await get_supabase()
    await db.table("wearable_connections").upsert({
        "user_id":  x_user_id,
        "provider": "fitbit",
        "status":   "pending",
        "metadata": json.dumps({"pkce_verifier": code_verifier, "state": state}),
    }, on_conflict="user_id,provider").execute()

    auth_url = build_auth_url(state=state, code_challenge=code_challenge)
    return {"auth_url": auth_url, "state": state}


class FitbitCallbackRequest(BaseModel):
    code:  str
    state: str


@router.post("/fitbit/callback")
async def fitbit_callback(
    req: FitbitCallbackRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """Exchange the authorization code for tokens and store them."""
    from services.wearables.fitbit import exchange_code
    db = await get_supabase()

    # Retrieve the PKCE verifier we stored
    conn_res = await db.table("wearable_connections").select("metadata").eq(
        "user_id", x_user_id
    ).eq("provider", "fitbit").single().execute()
    if not conn_res.data:
        raise HTTPException(404, "Fitbit connection not initiated")

    meta = json.loads(conn_res.data.get("metadata") or "{}")
    if meta.get("state") != req.state:
        raise HTTPException(400, "State mismatch — possible CSRF")

    code_verifier = meta.get("pkce_verifier")
    if not code_verifier:
        raise HTTPException(400, "Missing PKCE verifier")

    try:
        tokens = await exchange_code(req.code, code_verifier)
    except Exception as e:
        raise HTTPException(502, f"Fitbit token exchange failed: {e}")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 28800))

    await db.table("wearable_connections").update({
        "status":          "connected",
        "access_token":    tokens["access_token"],
        "refresh_token":   tokens.get("refresh_token"),
        "token_expires_at": expires_at.isoformat(),
        "scope":           tokens.get("scope"),
        "provider_user_id": tokens.get("user_id"),
        "last_synced_at":  None,
        "metadata":        json.dumps({}),
    }).eq("user_id", x_user_id).eq("provider", "fitbit").execute()

    log.info("fitbit.connected", user_id=x_user_id)

    # Kick off initial sync
    asyncio.create_task(_fitbit_sync_task(x_user_id, tokens["access_token"], since_days=30))

    return {"status": "connected", "message": "Fitbit connected. Initial sync started."}


@router.post("/fitbit/sync")
async def fitbit_sync(
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """Manually trigger a Fitbit sync."""
    access_token = await _get_valid_fitbit_token(x_user_id)
    db = await get_supabase()
    conn_res = await db.table("wearable_connections").select("last_synced_at").eq(
        "user_id", x_user_id
    ).eq("provider", "fitbit").single().execute()
    conn = conn_res.data

    # Sync from last sync date or 30 days ago
    last = conn.get("last_synced_at") if conn else None
    since_days = 30
    if last:
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        since_days = min(max(delta.days + 1, 1), 30)

    asyncio.create_task(_fitbit_sync_task(x_user_id, access_token, since_days=since_days))
    return {"status": "syncing", "since_days": since_days}


async def _fitbit_sync_task(user_id: str, access_token: str, since_days: int = 30):
    from services.wearables.fitbit import sync_fitbit_data
    try:
        since = date.today() - timedelta(days=since_days)
        events = await sync_fitbit_data(user_id, access_token, since_date=since)
        inserted = await _bulk_insert_events(user_id, events)
        asyncio.create_task(_store_wearable_episodes(user_id, events))
        db = await get_supabase()
        await db.table("wearable_connections").update({
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "sync_cursor":    date.today().isoformat(),
            "metadata":       json.dumps({"last_sync_count": inserted}),
        }).eq("user_id", user_id).eq("provider", "fitbit").execute()
        log.info("fitbit.sync_done", user_id=user_id, inserted=inserted)
    except Exception as e:
        log.error("fitbit.sync_failed", user_id=user_id, error=str(e), exc_info=True)


async def _get_valid_fitbit_token(user_id: str) -> str:
    """Return a valid Fitbit access token, refreshing if expired."""
    from services.wearables.fitbit import refresh_access_token
    db = await get_supabase()
    res = await db.table("wearable_connections").select(
        "access_token, refresh_token, token_expires_at, status"
    ).eq("user_id", user_id).eq("provider", "fitbit").single().execute()

    conn = res.data
    if not conn or conn.get("status") != "connected":
        raise HTTPException(404, "Fitbit not connected")

    # Refresh if within 5 minutes of expiry
    expires_at = conn.get("token_expires_at")
    if expires_at:
        exp = datetime.fromisoformat(expires_at)
        if datetime.now(timezone.utc) >= exp - timedelta(minutes=5):
            try:
                tokens = await refresh_access_token(conn["refresh_token"])
                new_exp = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 28800))
                await db.table("wearable_connections").update({
                    "access_token":    tokens["access_token"],
                    "refresh_token":   tokens.get("refresh_token", conn["refresh_token"]),
                    "token_expires_at": new_exp.isoformat(),
                }).eq("user_id", user_id).eq("provider", "fitbit").execute()
                return tokens["access_token"]
            except Exception as e:
                log.error("fitbit.refresh_failed", error=str(e), exc_info=True)
                raise HTTPException(502, "Could not refresh Fitbit token")

    return conn["access_token"]


# ─── Status + disconnect ──────────────────────────────────────────────────────

@router.get("/status")
async def wearables_status(
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """Return all wearable connection states for the user."""
    db = await get_supabase()
    res = await db.table("wearable_connections").select(
        "provider, status, last_synced_at, sync_cursor, provider_user_id"
    ).eq("user_id", x_user_id).execute()
    connections = {row["provider"]: row for row in (res.data or [])}

    result = {}
    for provider in SUPPORTED_PROVIDERS:
        conn = connections.get(provider)
        result[provider] = {
            "connected":     conn is not None and conn.get("status") == "connected",
            "last_synced_at": conn.get("last_synced_at") if conn else None,
        }
    return result


@router.delete("/{provider}")
async def disconnect_wearable(
    provider: str,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(400, f"Unknown provider: {provider}")
    db = await get_supabase()
    await db.table("wearable_connections").update({
        "status":        "disconnected",
        "access_token":  None,
        "refresh_token": None,
    }).eq("user_id", x_user_id).eq("provider", provider).execute()
    return {"status": "disconnected"}


# ─── Graphiti episode helper ─────────────────────────────────────────────────

async def _store_wearable_episodes(user_id: str, events: list[dict]) -> None:
    """
    Store daily aggregate episodes in Graphiti — one per (date, biomarker) pair.
    Avoids storing every individual reading (could be 50k+); instead computes
    the daily average and stores a single representative episode per biomarker per day.
    Capped at 200 episodes per sync call.
    """
    from services.memory import store_health_episode

    # Group by (date, biomarker_code)
    by_day_biomarker: dict[tuple[str, str], list[dict]] = {}
    for e in events:
        date_key = e.get("occurred_at", "")[:10]
        code = e.get("biomarker_code", "")
        if date_key and code:
            by_day_biomarker.setdefault((date_key, code), []).append(e)

    count = 0
    for (date_key, code), group in by_day_biomarker.items():
        if count >= 200:
            log.info("wearables.graphiti_cap_reached", user_id=user_id, stored=count)
            break
        values = [e["value_numeric"] for e in group if e.get("value_numeric") is not None]
        if not values:
            continue
        avg_val = round(sum(values) / len(values), 4)
        # Build a representative event dict with the daily average
        rep = dict(group[0])
        rep["value_numeric"] = avg_val
        rep["occurred_at"] = f"{date_key}T00:00:00+00:00"
        try:
            await store_health_episode(user_id, rep)
            count += 1
        except Exception as e:
            log.warning("wearables.graphiti_episode_failed", error=str(e), exc_info=True)

    log.info("wearables.graphiti_episodes_stored", user_id=user_id, stored=count)


# ─── Shared insert helper ─────────────────────────────────────────────────────

async def _bulk_insert_events(user_id: str, events: list[dict]) -> int:
    """
    Insert health events in batches of 500.
    Uses upsert on (user_id, biomarker_code, occurred_at) to deduplicate.
    Also upserts into Qdrant for vector search.
    """
    if not events:
        return 0

    db = await get_supabase()
    inserted = 0
    batch_size = 500

    for i in range(0, len(events), batch_size):
        batch = events[i : i + batch_size]
        try:
            res = await db.table("health_events").upsert(
                batch,
                on_conflict="user_id,biomarker_code,occurred_at",
                ignore_duplicates=True,
            ).execute()
            inserted += len(res.data or [])
        except Exception as e:
            log.error("wearables.insert_failed", batch_start=i, error=str(e), exc_info=True)

    # Qdrant upsert — fire and forget per event (non-blocking)
    async def _upsert_all():
        for event in events:
            try:
                event_id = f"{user_id}:{event['biomarker_code']}:{event['occurred_at']}"
                await upsert_health_event(event_id, user_id, event)
            except Exception as e:
                log.warning("wearables.qdrant_upsert_failed", error=str(e), exc_info=True)

    asyncio.create_task(_upsert_all())
    return inserted
