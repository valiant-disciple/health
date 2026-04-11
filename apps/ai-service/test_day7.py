"""
Day 7 tests: interpretation service, LOINC lookup, status derivation,
and the /interpret/report endpoint (mocked OpenAI + Supabase).
"""
import json
import pytest
import sys
import os

# Allow importing from project root
sys.path.insert(0, os.path.dirname(__file__))

# ─── Unit tests: LOINC lookup ─────────────────────────────────────────────────

from services.ocr import _lookup_loinc, LOINC_MAP


def test_loinc_exact_match():
    assert _lookup_loinc("glucose") == "2345-7"


def test_loinc_case_insensitive():
    assert _lookup_loinc("Hemoglobin") == "718-7"


def test_loinc_substring_match():
    # "a1c" key matches before "hemoglobin a1c" key — both map to the same code
    assert _lookup_loinc("HbA1c") == "4548-4"


def test_loinc_unknown_returns_empty():
    assert _lookup_loinc("xyznonexistenttest") == ""


def test_loinc_tsh():
    assert _lookup_loinc("TSH (thyroid stimulating hormone)") == "3016-3"


def test_loinc_vitamin_d():
    assert _lookup_loinc("25-Hydroxy Vitamin D") == "1989-3"


# ─── Unit tests: _derive_status ──────────────────────────────────────────────

# Import the internal function directly
from services.ocr import _derive_status  # type: ignore[attr-defined]


def test_status_normal():
    assert _derive_status(5.0, 4.0, 10.0, None) == "normal"


def test_status_high():
    assert _derive_status(12.0, 4.0, 10.0, "H") == "high"


def test_status_low():
    assert _derive_status(2.0, 4.0, 10.0, "L") == "low"


def test_status_critical_high():
    # >1.5× ref_high triggers critical (flag check is skipped when flag=None)
    assert _derive_status(16.0, 4.0, 10.0, None) == "critical"


def test_status_critical_low():
    # <50% ref_low triggers critical (flag check is skipped when flag=None)
    assert _derive_status(1.5, 4.0, 10.0, None) == "critical"


def test_status_flag_overrides_magnitude():
    # Flag "H" returns "high" even if value is critical magnitude
    assert _derive_status(25.0, 4.0, 10.0, "H") == "high"


def test_status_critical_via_flag():
    assert _derive_status(25.0, 4.0, 10.0, "HH") == "critical"


def test_status_no_range_flag_H():
    assert _derive_status(999.0, None, None, "H") == "high"


def test_status_no_range_no_flag():
    assert _derive_status(999.0, None, None, None) == "normal"


# ─── Unit tests: interpretation JSON parsing ─────────────────────────────────

import re


def _extract_json(text: str) -> dict:
    """Mirror of the JSON extraction logic in routers/interpret.py."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON found")
    return json.loads(match.group())


SAMPLE_INTERPRETATION = {
    "summary": "Overall results look healthy.",
    "key_findings": [
        {
            "loinc": "2345-7",
            "name": "Glucose",
            "value": "95 mg/dL",
            "status": "normal",
            "explanation": "Within normal range.",
            "trend": "stable",
            "previous_value": None,
            "previous_date": None,
        }
    ],
    "dietary_suggestions": [],
    "lifestyle_suggestions": [],
    "drug_nutrient_flags": [],
    "discuss_with_doctor": [],
}


def test_json_extraction_from_plain_json():
    text = json.dumps(SAMPLE_INTERPRETATION)
    result = _extract_json(text)
    assert result["summary"] == "Overall results look healthy."
    assert result["key_findings"][0]["loinc"] == "2345-7"


def test_json_extraction_from_prose_with_json():
    text = (
        "Here is the interpretation:\n"
        + json.dumps(SAMPLE_INTERPRETATION)
        + "\nEnd of output."
    )
    result = _extract_json(text)
    assert result["key_findings"][0]["status"] == "normal"


def test_json_extraction_fails_on_no_json():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _extract_json("No JSON here at all.")


# ─── Integration test: /interpret/report endpoint (mocked) ───────────────────

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from main import app


@pytest.fixture()
def client():
    return TestClient(app)


MOCK_LAB_RESULTS = [
    {
        "loinc_code": "2345-7",
        "loinc_name": "Glucose",
        "value_numeric": 95.0,
        "unit": "mg/dL",
        "ref_range_low": 70,
        "ref_range_high": 100,
        "status": "normal",
        "flag": None,
    }
]


def _make_openai_response(content: str):
    """Build a minimal mock OpenAI response object."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_interpret_report_success(client):
    mock_result = MagicMock()
    mock_result.interpretation = json.dumps(SAMPLE_INTERPRETATION)
    mock_program = MagicMock(return_value=mock_result)
    with (
        patch("routers.interpret.get_lab_results_for_report", new=AsyncMock(return_value=MOCK_LAB_RESULTS)),
        patch("routers.interpret.assemble_patient_artifact", new=AsyncMock(return_value={"profile": {}})),
        patch("routers.interpret.run_guardrails", new=AsyncMock(return_value=(json.dumps(SAMPLE_INTERPRETATION), True, []))),
        patch("routers.interpret.extract_and_store_facts", new=AsyncMock()),
        patch("routers.interpret.get_interpret_program", return_value=mock_program),
    ):
        response = client.post(
            "/interpret/report",
            json={"user_id": "user-123", "report_id": "report-456"},
            headers={"X-User-Id": "user-123"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "interpretation" in data
    assert data["interpretation"]["summary"] == "Overall results look healthy."


def test_interpret_report_user_mismatch(client):
    response = client.post(
        "/interpret/report",
        json={"user_id": "user-123", "report_id": "report-456"},
        headers={"X-User-Id": "user-different"},
    )
    assert response.status_code == 403


def test_interpret_report_not_found(client):
    with patch("routers.interpret.get_lab_results_for_report", new=AsyncMock(return_value=[])):
        response = client.post(
            "/interpret/report",
            json={"user_id": "user-123", "report_id": "report-999"},
            headers={"X-User-Id": "user-123"},
        )
    assert response.status_code == 404


def test_interpret_report_guardrail_blocked(client):
    mock_result = MagicMock()
    mock_result.interpretation = "blocked"
    mock_program = MagicMock(return_value=mock_result)
    with (
        patch("routers.interpret.get_lab_results_for_report", new=AsyncMock(return_value=MOCK_LAB_RESULTS)),
        patch("routers.interpret.assemble_patient_artifact", new=AsyncMock(return_value={})),
        patch("routers.interpret.run_guardrails", new=AsyncMock(return_value=("", False, []))),
        patch("routers.interpret.get_interpret_program", return_value=mock_program),
    ):
        response = client.post(
            "/interpret/report",
            json={"user_id": "user-123", "report_id": "report-456"},
            headers={"X-User-Id": "user-123"},
        )
    assert response.status_code == 422
