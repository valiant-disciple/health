"""
Fitbit API client — OAuth2 PKCE flow + data sync.
Docs: https://dev.fitbit.com/build/reference/web-api/

Required env vars:
  FITBIT_CLIENT_ID      — from dev.fitbit.com app registration
  FITBIT_CLIENT_SECRET  — from dev.fitbit.com app registration
  FITBIT_REDIRECT_URI   — must match exactly what's registered (e.g. http://localhost:3000/wearables/fitbit/callback)
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import structlog

from services.wearables.normalize import FITBIT_TYPE_MAP, to_health_event

log = structlog.get_logger()

FITBIT_AUTH_URL  = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"
FITBIT_API_BASE  = "https://api.fitbit.com/1"
FITBIT_API_USER  = "https://api.fitbit.com/1/user/-"

FITBIT_SCOPES = " ".join([
    "activity", "heartrate", "sleep", "weight",
    "oxygen_saturation", "respiratory_rate", "profile",
])


def get_fitbit_credentials():
    client_id     = os.environ.get("FITBIT_CLIENT_ID", "")
    client_secret = os.environ.get("FITBIT_SECRET", "")
    redirect_uri  = os.environ.get("FITBIT_REDIRECT_URI", "http://localhost:3000/wearables/fitbit/callback")
    if not client_id:
        raise ValueError("FITBIT_CLIENT_ID env var not set")
    return client_id, client_secret, redirect_uri


# ─── OAuth2 PKCE ──────────────────────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE flow."""
    verifier  = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(state: str, code_challenge: str) -> str:
    """Build the Fitbit authorization URL to redirect the user to."""
    client_id, _, redirect_uri = get_fitbit_credentials()
    params = {
        "response_type":          "code",
        "client_id":              client_id,
        "redirect_uri":           redirect_uri,
        "scope":                  FITBIT_SCOPES,
        "state":                  state,
        "code_challenge":         code_challenge,
        "code_challenge_method":  "S256",
    }
    return f"{FITBIT_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    client_id, client_secret, redirect_uri = get_fitbit_credentials()
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            FITBIT_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "client_id":     client_id,
                "grant_type":    "authorization_code",
                "redirect_uri":  redirect_uri,
                "code":          code,
                "code_verifier": code_verifier,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an expired access token."""
    client_id, client_secret, _ = get_fitbit_credentials()
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            FITBIT_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        return resp.json()


# ─── Data sync ────────────────────────────────────────────────────────────────

async def sync_fitbit_data(
    user_id: str,
    access_token: str,
    since_date: date | None = None,
) -> list[dict]:
    """
    Fetch 30 days of Fitbit data (or from since_date) and return health_event dicts.
    Fetches: heart rate, sleep, steps/activity, weight, SpO2.
    """
    since  = since_date or (date.today() - timedelta(days=30))
    today  = date.today()
    events: list[dict] = []

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        # Heart rate — intraday is rate-limited; use daily summary
        events += await _fetch_heart_rate(client, user_id, since, today)
        # Activity (steps, calories, distance)
        events += await _fetch_activity(client, user_id, since, today)
        # Sleep
        events += await _fetch_sleep(client, user_id, since, today)
        # Body weight
        events += await _fetch_body(client, user_id, since, today)
        # SpO2 (requires SpO2 scope + Fitbit Premium for some users)
        events += await _fetch_spo2(client, user_id, since, today)

    log.info("fitbit.synced", user_id=user_id, n_events=len(events))
    return events


async def _fetch_heart_rate(
    client: httpx.AsyncClient,
    user_id: str,
    since: date,
    until: date,
) -> list[dict]:
    events = []
    try:
        resp = await client.get(
            f"{FITBIT_API_USER}/activities/heart/date/{since.isoformat()}/{until.isoformat()}.json"
        )
        resp.raise_for_status()
        for day in resp.json().get("activities-heart", []):
            dt   = day.get("dateTime")
            vals = day.get("value", {})
            rhr  = vals.get("restingHeartRate")
            if rhr and dt:
                events.append(to_health_event(
                    user_id=user_id,
                    mapping=FITBIT_TYPE_MAP["resting_hr"],
                    value=rhr,
                    occurred_at=f"{dt}T00:00:00+00:00",
                    source="fitbit",
                    metadata={"zones": vals.get("heartRateZones", [])},
                ))
    except Exception as e:
        log.warning("fitbit.heart_rate_failed", error=str(e))
    return events


async def _fetch_activity(
    client: httpx.AsyncClient,
    user_id: str,
    since: date,
    until: date,
) -> list[dict]:
    events = []
    endpoints = [
        ("steps",           "steps",          FITBIT_TYPE_MAP["steps"]),
        ("calories",        "calories_active", FITBIT_TYPE_MAP["calories_active"]),
        ("distance",        "distance_km",     FITBIT_TYPE_MAP["distance_km"]),
    ]
    for resource, key, mapping in endpoints:
        try:
            resp = await client.get(
                f"{FITBIT_API_USER}/activities/{resource}/date/{since.isoformat()}/{until.isoformat()}.json"
            )
            resp.raise_for_status()
            for day in resp.json().get(f"activities-{resource}", []):
                dt  = day.get("dateTime")
                val = day.get("value")
                if val and dt and float(val) > 0:
                    # Fitbit returns distance in km
                    events.append(to_health_event(
                        user_id=user_id,
                        mapping=mapping,
                        value=float(val),
                        occurred_at=f"{dt}T00:00:00+00:00",
                        source="fitbit",
                    ))
        except Exception as e:
            log.warning(f"fitbit.{resource}_failed", error=str(e))
    return events


async def _fetch_sleep(
    client: httpx.AsyncClient,
    user_id: str,
    since: date,
    until: date,
) -> list[dict]:
    events = []
    try:
        resp = await client.get(
            f"{FITBIT_API_USER}/sleep/date/{since.isoformat()}/{until.isoformat()}.json"
        )
        resp.raise_for_status()
        for log_entry in resp.json().get("sleep", []):
            if log_entry.get("isMainSleep"):
                dt = log_entry.get("dateOfSleep")
                minutes = log_entry.get("minutesAsleep", 0)
                if minutes > 0 and dt:
                    events.append(to_health_event(
                        user_id=user_id,
                        mapping=FITBIT_TYPE_MAP["minutes_asleep"],
                        value=minutes / 60,  # convert to hours
                        occurred_at=f"{dt}T00:00:00+00:00",
                        source="fitbit",
                        metadata={
                            "stages":       log_entry.get("levels", {}).get("summary", {}),
                            "efficiency":   log_entry.get("efficiency"),
                            "minutes_deep": log_entry.get("levels", {}).get("summary", {}).get("deep", {}).get("minutes"),
                        },
                    ))
    except Exception as e:
        log.warning("fitbit.sleep_failed", error=str(e))
    return events


async def _fetch_body(
    client: httpx.AsyncClient,
    user_id: str,
    since: date,
    until: date,
) -> list[dict]:
    events = []
    try:
        resp = await client.get(
            f"{FITBIT_API_USER}/body/log/weight/date/{since.isoformat()}/{until.isoformat()}.json"
        )
        resp.raise_for_status()
        for entry in resp.json().get("weight", []):
            dt  = entry.get("date")
            bmi = entry.get("bmi")
            w   = entry.get("weight")  # Fitbit returns kg if metric is set
            fat = entry.get("fat")
            if dt:
                if w:
                    events.append(to_health_event(
                        user_id=user_id, mapping=FITBIT_TYPE_MAP["weight_kg"],
                        value=w, occurred_at=f"{dt}T00:00:00+00:00", source="fitbit",
                    ))
                if bmi:
                    events.append(to_health_event(
                        user_id=user_id, mapping=FITBIT_TYPE_MAP["bmi"],
                        value=bmi, occurred_at=f"{dt}T00:00:00+00:00", source="fitbit",
                    ))
                if fat:
                    events.append(to_health_event(
                        user_id=user_id, mapping=FITBIT_TYPE_MAP["fat_pct"],
                        value=fat, occurred_at=f"{dt}T00:00:00+00:00", source="fitbit",
                    ))
    except Exception as e:
        log.warning("fitbit.body_failed", error=str(e))
    return events


async def _fetch_spo2(
    client: httpx.AsyncClient,
    user_id: str,
    since: date,
    until: date,
) -> list[dict]:
    events = []
    try:
        resp = await client.get(
            f"{FITBIT_API_USER}/spo2/date/{since.isoformat()}/{until.isoformat()}.json"
        )
        resp.raise_for_status()
        for entry in resp.json():
            dt   = entry.get("dateTime")
            val  = entry.get("value", {}).get("avg")
            if dt and val:
                events.append(to_health_event(
                    user_id=user_id,
                    mapping=FITBIT_TYPE_MAP["spo2"],
                    value=val,
                    occurred_at=f"{dt}T00:00:00+00:00",
                    source="fitbit",
                ))
    except Exception as e:
        log.warning("fitbit.spo2_failed", error=str(e))
    return events
