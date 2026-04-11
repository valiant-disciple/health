"""
Day 8 tests — Wearable ingestion
  - normalize.py: to_health_event shape, LOINC maps
  - apple_health.py: XML parsing, zip extraction, lb→kg conversion, sleep calc, MAX_RECORDS cap
  - fitbit.py: PKCE pair generation + challenge correctness, sync response shaping
  - wearables router: upload endpoint, status endpoint, disconnect, bulk insert
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import zipfile
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _make_xml(records: list[dict]) -> bytes:
    """Build a minimal Apple Health export.xml from a list of Record dicts."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<HealthData>"]
    for r in records:
        attrs = " ".join(f'{k}="{v}"' for k, v in r.items())
        lines.append(f"  <Record {attrs}/>")
    lines.append("</HealthData>")
    return "\n".join(lines).encode()


def _make_zip(xml_bytes: bytes) -> bytes:
    """Wrap export.xml bytes in a zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("apple_health_export/export.xml", xml_bytes)
    return buf.getvalue()


VALID_DATE = "2024-06-15 09:23:00 +0000"
RECENT_DATE = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S +0000")

HR_RECORD = {
    "type": "HKQuantityTypeIdentifierHeartRate",
    "sourceName": "Apple Watch",
    "value": "72",
    "unit": "count/min",
    "startDate": RECENT_DATE,
    "endDate": RECENT_DATE,
}

WEIGHT_LBS_RECORD = {
    "type": "HKQuantityTypeIdentifierBodyMass",
    "sourceName": "Apple Health",
    "value": "154",   # 154 lbs ≈ 69.85 kg
    "unit": "lb",
    "startDate": RECENT_DATE,
    "endDate": RECENT_DATE,
}

SLEEP_RECORD = {
    "type": "HKCategoryTypeIdentifierSleepAnalysis",
    "sourceName": "iPhone",
    "value": "HKCategoryValueSleepAnalysisAsleep",
    "unit": "",
    "startDate": RECENT_DATE,
    "endDate": (datetime.now(timezone.utc) - timedelta(days=10) + timedelta(hours=7, minutes=30)).strftime("%Y-%m-%d %H:%M:%S +0000"),
}


# ══════════════════════════════════════════════════════════════════════
# 1. normalize.py
# ══════════════════════════════════════════════════════════════════════

class TestNormalize:
    def setup_method(self):
        from services.wearables.normalize import APPLE_TYPE_MAP, FITBIT_TYPE_MAP, to_health_event
        self.APPLE_TYPE_MAP = APPLE_TYPE_MAP
        self.FITBIT_TYPE_MAP = FITBIT_TYPE_MAP
        self.to_health_event = to_health_event

    def test_apple_type_map_has_required_keys(self):
        required = {
            "HKQuantityTypeIdentifierHeartRate",
            "HKQuantityTypeIdentifierRestingHeartRate",
            "HKQuantityTypeIdentifierStepCount",
            "HKQuantityTypeIdentifierBodyMass",
            "HKCategoryTypeIdentifierSleepAnalysis",
            "HKQuantityTypeIdentifierOxygenSaturation",
        }
        assert required.issubset(self.APPLE_TYPE_MAP.keys())

    def test_fitbit_type_map_has_required_keys(self):
        required = {"heart_rate", "resting_hr", "steps", "weight_kg", "minutes_asleep", "spo2"}
        assert required.issubset(self.FITBIT_TYPE_MAP.keys())

    def test_every_apple_mapping_has_loinc(self):
        for key, m in self.APPLE_TYPE_MAP.items():
            assert "loinc" in m, f"Missing loinc in {key}"
            assert m["loinc"], f"Empty loinc in {key}"

    def test_every_fitbit_mapping_has_loinc(self):
        for key, m in self.FITBIT_TYPE_MAP.items():
            assert "loinc" in m, f"Missing loinc in {key}"

    def test_to_health_event_required_fields(self):
        mapping = self.FITBIT_TYPE_MAP["resting_hr"]
        evt = self.to_health_event(
            user_id="user-1",
            mapping=mapping,
            value=62.0,
            occurred_at="2024-06-15T00:00:00+00:00",
            source="fitbit",
        )
        assert evt["user_id"] == "user-1"
        assert evt["biomarker_code"] == "40443-4"
        assert evt["biomarker_name"] == "Resting Heart Rate"
        assert evt["value_numeric"] == 62.0
        assert evt["unit"] == "bpm"
        assert evt["source"] == "fitbit"
        assert evt["event_type"] == "heart_rate"
        assert "recorded_at" in evt

    def test_to_health_event_value_rounded_to_4dp(self):
        mapping = self.FITBIT_TYPE_MAP["bmi"]
        evt = self.to_health_event("u", mapping, 23.456789, "2024-01-01T00:00:00+00:00", "fitbit")
        assert evt["value_numeric"] == round(23.456789, 4)

    def test_to_health_event_source_device_passthrough(self):
        mapping = self.APPLE_TYPE_MAP["HKQuantityTypeIdentifierHeartRate"]
        evt = self.to_health_event("u", mapping, 70, "2024-01-01T00:00:00+00:00", "apple_health", source_device="Apple Watch")
        assert evt["source_device"] == "Apple Watch"

    def test_to_health_event_status_is_normal(self):
        mapping = self.FITBIT_TYPE_MAP["steps"]
        evt = self.to_health_event("u", mapping, 8000, "2024-01-01T00:00:00+00:00", "fitbit")
        assert evt["status"] == "normal"


# ══════════════════════════════════════════════════════════════════════
# 2. apple_health.py
# ══════════════════════════════════════════════════════════════════════

class TestAppleHealthParser:
    def setup_method(self):
        from services.wearables.apple_health import (
            parse_apple_health_export,
            _extract_xml,
            _parse_apple_date,
        )
        self.parse = parse_apple_health_export
        self.extract_xml = _extract_xml
        self.parse_date = _parse_apple_date

    # Date parsing
    def test_parse_apple_date_standard(self):
        dt = self.parse_date("2024-06-15 09:23:00 +0000")
        assert dt is not None
        assert dt.year == 2024 and dt.month == 6 and dt.day == 15

    def test_parse_apple_date_iso_format(self):
        dt = self.parse_date("2024-06-15T09:23:00+00:00")
        assert dt is not None
        assert dt.hour == 9

    def test_parse_apple_date_empty_returns_none(self):
        assert self.parse_date("") is None

    def test_parse_apple_date_invalid_returns_none(self):
        assert self.parse_date("not-a-date") is None

    # Zip extraction
    def test_extract_xml_from_zip(self):
        xml = b"<HealthData/>"
        zipped = _make_zip(xml)
        extracted = self.extract_xml(zipped)
        assert extracted == xml

    def test_extract_xml_from_raw_xml(self):
        xml = b"<HealthData/>"
        assert self.extract_xml(xml) == xml

    def test_extract_xml_zip_missing_export_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("something_else.txt", "hello")
        with pytest.raises(ValueError, match="No export.xml"):
            self.extract_xml(buf.getvalue())

    # Heart rate parsing
    def test_parse_heart_rate_record(self):
        xml = _make_xml([HR_RECORD])
        events = self.parse(xml, "user-abc")
        assert len(events) == 1
        assert events[0]["biomarker_code"] == "8867-4"
        assert events[0]["value_numeric"] == 72.0
        assert events[0]["source"] == "apple_health"
        assert events[0]["source_device"] == "Apple Watch"

    # lbs → kg conversion
    def test_weight_lbs_converted_to_kg(self):
        xml = _make_xml([WEIGHT_LBS_RECORD])
        events = self.parse(xml, "user-abc")
        assert len(events) == 1
        # 154 lbs * 0.453592 ≈ 69.8532
        assert abs(events[0]["value_numeric"] - 69.8532) < 0.01

    # Sleep duration calculation
    def test_sleep_duration_calculated_from_start_end(self):
        xml = _make_xml([SLEEP_RECORD])
        events = self.parse(xml, "user-abc")
        assert len(events) == 1
        assert events[0]["biomarker_code"] == "93832-4"
        # 7h30m = 7.5 hours
        assert abs(events[0]["value_numeric"] - 7.5) < 0.1

    # Old data filtered out by lookback
    def test_old_records_excluded(self):
        old_record = dict(HR_RECORD, startDate="2020-01-01 00:00:00 +0000", endDate="2020-01-01 00:00:00 +0000")
        xml = _make_xml([old_record])
        events = self.parse(xml, "user-abc", lookback_days=365)
        assert len(events) == 0

    # Unknown type is silently skipped
    def test_unknown_type_skipped(self):
        unknown = dict(HR_RECORD, type="HKUnknownType")
        xml = _make_xml([unknown])
        events = self.parse(xml, "user-abc")
        assert len(events) == 0

    # MAX_RECORDS guard
    def test_max_records_cap(self):
        from services.wearables import apple_health as ah_module
        orig = ah_module.MAX_RECORDS
        ah_module.MAX_RECORDS = 3
        try:
            records = [dict(HR_RECORD) for _ in range(10)]
            xml = _make_xml(records)
            events = self.parse(xml, "user-abc")
            assert len(events) <= 3
        finally:
            ah_module.MAX_RECORDS = orig

    # ZIP ingestion end-to-end
    def test_parse_from_zip(self):
        xml = _make_xml([HR_RECORD])
        zipped = _make_zip(xml)
        events = self.parse(zipped, "user-abc")
        assert len(events) == 1

    # metadata carries hk_type
    def test_metadata_carries_hk_type(self):
        xml = _make_xml([HR_RECORD])
        events = self.parse(xml, "user-abc")
        assert events[0]["metadata"]["hk_type"] == "HKQuantityTypeIdentifierHeartRate"


# ══════════════════════════════════════════════════════════════════════
# 3. fitbit.py — PKCE + sync output shape
# ══════════════════════════════════════════════════════════════════════

class TestFitbitPKCE:
    def setup_method(self):
        from services.wearables.fitbit import generate_pkce_pair, build_auth_url
        self.generate_pkce_pair = generate_pkce_pair
        self.build_auth_url = build_auth_url

    def test_pkce_pair_returns_two_strings(self):
        verifier, challenge = self.generate_pkce_pair()
        assert isinstance(verifier, str) and len(verifier) > 40
        assert isinstance(challenge, str) and len(challenge) > 20

    def test_pkce_challenge_is_sha256_base64url(self):
        verifier, challenge = self.generate_pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert challenge == expected

    def test_pkce_pairs_are_unique(self):
        v1, c1 = self.generate_pkce_pair()
        v2, c2 = self.generate_pkce_pair()
        assert v1 != v2
        assert c1 != c2

    def test_pkce_challenge_no_padding(self):
        _, challenge = self.generate_pkce_pair()
        assert "=" not in challenge

    def test_build_auth_url_includes_required_params(self):
        with patch("services.wearables.fitbit.get_fitbit_credentials",
                   return_value=("client123", "secret", "http://localhost:3000/wearables/fitbit/callback")):
            url = self.build_auth_url("mystate", "mychallenge")
        assert "client_id=client123" in url
        assert "state=mystate" in url
        assert "code_challenge=mychallenge" in url
        assert "code_challenge_method=S256" in url
        assert "response_type=code" in url

    def test_build_auth_url_includes_all_scopes(self):
        with patch("services.wearables.fitbit.get_fitbit_credentials",
                   return_value=("cid", "sec", "http://localhost/cb")):
            url = self.build_auth_url("s", "c")
        assert "heartrate" in url
        assert "activity" in url
        assert "sleep" in url


class TestFitbitSync:
    """Tests for sync_fitbit_data using mocked httpx responses."""

    def _mock_response(self, json_data: dict | list, status_code: int = 200):
        m = MagicMock()
        m.status_code = status_code
        m.json.return_value = json_data
        m.raise_for_status = MagicMock()
        return m

    async def test_sync_returns_resting_hr_events(self):
        from services.wearables.fitbit import _fetch_heart_rate
        mock_client = AsyncMock()
        mock_client.get.return_value = self._mock_response({
            "activities-heart": [
                {"dateTime": "2024-06-15", "value": {"restingHeartRate": 62}},
                {"dateTime": "2024-06-16", "value": {"restingHeartRate": 64}},
            ]
        })
        events = await _fetch_heart_rate(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 16))
        assert len(events) == 2
        assert all(e["biomarker_code"] == "40443-4" for e in events)
        assert events[0]["value_numeric"] == 62
        assert events[1]["value_numeric"] == 64

    async def test_sync_heart_rate_skips_missing_rhr(self):
        from services.wearables.fitbit import _fetch_heart_rate
        mock_client = AsyncMock()
        mock_client.get.return_value = self._mock_response({
            "activities-heart": [
                {"dateTime": "2024-06-15", "value": {}},  # no restingHeartRate
            ]
        })
        events = await _fetch_heart_rate(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 15))
        assert len(events) == 0

    async def test_sync_sleep_converts_minutes_to_hours(self):
        from services.wearables.fitbit import _fetch_sleep
        mock_client = AsyncMock()
        mock_client.get.return_value = self._mock_response({
            "sleep": [
                {"isMainSleep": True, "dateOfSleep": "2024-06-15", "minutesAsleep": 450},
            ]
        })
        events = await _fetch_sleep(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 15))
        assert len(events) == 1
        assert events[0]["value_numeric"] == pytest.approx(7.5, abs=0.01)
        assert events[0]["biomarker_code"] == "93832-4"

    async def test_sync_sleep_skips_non_main_sleep(self):
        from services.wearables.fitbit import _fetch_sleep
        mock_client = AsyncMock()
        mock_client.get.return_value = self._mock_response({
            "sleep": [
                {"isMainSleep": False, "dateOfSleep": "2024-06-15", "minutesAsleep": 60},
            ]
        })
        events = await _fetch_sleep(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 15))
        assert len(events) == 0

    async def test_sync_body_produces_weight_bmi_fat(self):
        from services.wearables.fitbit import _fetch_body
        mock_client = AsyncMock()
        mock_client.get.return_value = self._mock_response({
            "weight": [
                {"date": "2024-06-15", "weight": 75.0, "bmi": 24.2, "fat": 18.5},
            ]
        })
        events = await _fetch_body(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 15))
        loincs = {e["biomarker_code"] for e in events}
        assert "29463-7" in loincs  # weight
        assert "39156-5" in loincs  # BMI
        assert "41982-0" in loincs  # body fat

    async def test_sync_http_error_returns_empty_not_raises(self):
        """Partial failure must not crash the whole sync."""
        from services.wearables.fitbit import _fetch_heart_rate
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("network error")
        # Should not raise
        events = await _fetch_heart_rate(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 15))
        assert events == []

    async def test_sync_spo2(self):
        from services.wearables.fitbit import _fetch_spo2
        mock_client = AsyncMock()
        mock_client.get.return_value = self._mock_response([
            {"dateTime": "2024-06-15", "value": {"avg": 97.5}},
        ])
        events = await _fetch_spo2(mock_client, "user-1", date(2024, 6, 15), date(2024, 6, 15))
        assert len(events) == 1
        assert events[0]["biomarker_code"] == "2708-6"
        assert events[0]["value_numeric"] == pytest.approx(97.5)


# ══════════════════════════════════════════════════════════════════════
# 4. Wearable router endpoints
# ══════════════════════════════════════════════════════════════════════

def _make_supabase_mock(rows: list | None = None, single_row: dict | None = None):
    """Build a chainable Supabase async mock."""
    db = MagicMock()

    def _build_chain(return_data):
        result = MagicMock()
        result.data = return_data
        execute_mock = AsyncMock(return_value=result)
        chain = MagicMock()
        chain.execute = execute_mock
        chain.eq = MagicMock(return_value=chain)
        chain.select = MagicMock(return_value=chain)
        chain.update = MagicMock(return_value=chain)
        chain.upsert = MagicMock(return_value=chain)
        chain.single = MagicMock(return_value=chain)
        return chain

    db.table = MagicMock(return_value=_build_chain(rows if rows is not None else (single_row and [single_row]) or []))
    return db


class TestWearableRouter:
    def setup_method(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from routers.wearables import router as wearables_router
        app = FastAPI()
        app.include_router(wearables_router, prefix="/wearables")
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_status_returns_both_providers(self):
        with patch("routers.wearables.get_supabase") as mock_db:
            db = MagicMock()
            result = MagicMock()
            result.data = [
                {"provider": "fitbit", "status": "connected", "last_synced_at": "2024-06-15T12:00:00+00:00", "sync_cursor": None, "provider_user_id": "fb-123"},
            ]
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.execute = AsyncMock(return_value=result)
            db.table.return_value = chain
            mock_db.return_value = db

            resp = self.client.get("/wearables/status", headers={"X-User-Id": "user-1"})

        assert resp.status_code == 200
        data = resp.json()
        assert "fitbit" in data
        assert "apple_health" in data
        assert data["fitbit"]["connected"] is True
        assert data["apple_health"]["connected"] is False

    def test_disconnect_returns_disconnected(self):
        with patch("routers.wearables.get_supabase") as mock_db:
            db = MagicMock()
            result = MagicMock()
            result.data = []
            chain = MagicMock()
            chain.update.return_value = chain
            chain.eq.return_value = chain
            chain.execute = AsyncMock(return_value=result)
            db.table.return_value = chain
            mock_db.return_value = db

            resp = self.client.delete("/wearables/fitbit", headers={"X-User-Id": "user-1"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

    def test_disconnect_unknown_provider_400(self):
        resp = self.client.delete("/wearables/unknown_provider", headers={"X-User-Id": "user-1"})
        assert resp.status_code == 400

    def test_apple_health_upload_wrong_extension_400(self):
        from io import BytesIO
        resp = self.client.post(
            "/wearables/apple-health/upload",
            headers={"X-User-Id": "user-1"},
            files={"file": ("data.csv", BytesIO(b"data"), "text/csv")},
        )
        assert resp.status_code == 400

    def test_apple_health_upload_valid_xml_accepted(self):
        xml = _make_xml([HR_RECORD])
        with patch("routers.wearables.get_supabase") as mock_db, \
             patch("routers.wearables._process_apple_upload") as mock_task:
            # Mock _process_apple_upload to be a coroutine that returns immediately
            mock_task.return_value = None

            db = MagicMock()
            result = MagicMock()
            result.data = []
            chain = MagicMock()
            chain.upsert.return_value = chain
            chain.eq.return_value = chain
            chain.execute = AsyncMock(return_value=result)
            db.table.return_value = chain
            mock_db.return_value = db

            resp = self.client.post(
                "/wearables/apple-health/upload",
                headers={"X-User-Id": "user-1"},
                files={"file": ("export.xml", io.BytesIO(xml), "application/xml")},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_fitbit_connect_raises_503_when_no_client_id(self):
        with patch("services.wearables.fitbit.get_fitbit_credentials", side_effect=ValueError("FITBIT_CLIENT_ID env var not set")):
            resp = self.client.get("/wearables/fitbit/connect", headers={"X-User-Id": "user-1"})
        assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════
# 5. _bulk_insert_events deduplication logic
# ══════════════════════════════════════════════════════════════════════

class TestBulkInsert:
    async def test_empty_events_returns_zero(self):
        from routers.wearables import _bulk_insert_events
        with patch("routers.wearables.get_supabase") as mock_db:
            result = await _bulk_insert_events("user-1", [])
        assert result == 0
        mock_db.assert_not_called()

    async def test_insert_calls_upsert_with_conflict_keys(self):
        from routers.wearables import _bulk_insert_events
        events = [
            {"user_id": "u", "biomarker_code": "8867-4", "occurred_at": "2024-01-01T00:00:00+00:00", "value_numeric": 72},
        ]
        with patch("routers.wearables.get_supabase") as mock_db, \
             patch("asyncio.create_task"):
            db = MagicMock()
            result = MagicMock()
            result.data = events
            chain = MagicMock()
            chain.upsert.return_value = chain
            chain.execute = AsyncMock(return_value=result)
            db.table.return_value = chain
            mock_db.return_value = db

            n = await _bulk_insert_events("user-1", events)

        assert n == 1
        # Verify upsert was called with the conflict keys
        call_kwargs = chain.upsert.call_args
        assert call_kwargs[1]["on_conflict"] == "user_id,biomarker_code,occurred_at"
        assert call_kwargs[1]["ignore_duplicates"] is True

    async def test_insert_batches_at_500(self):
        from routers.wearables import _bulk_insert_events
        # 1001 events → 3 batches (500 + 500 + 1)
        events = [
            {"user_id": "u", "biomarker_code": f"code-{i}", "occurred_at": f"2024-01-{(i%28)+1:02d}T00:00:00+00:00", "value_numeric": i}
            for i in range(1001)
        ]
        with patch("routers.wearables.get_supabase") as mock_db, \
             patch("asyncio.create_task"):
            db = MagicMock()
            result = MagicMock()
            result.data = []  # actual count not critical here
            chain = MagicMock()
            chain.upsert.return_value = chain
            chain.execute = AsyncMock(return_value=result)
            db.table.return_value = chain
            mock_db.return_value = db

            await _bulk_insert_events("user-1", events)

        # upsert called 3 times
        assert chain.upsert.call_count == 3
        # Verify first batch size
        first_call_data = chain.upsert.call_args_list[0][0][0]
        assert len(first_call_data) == 500
