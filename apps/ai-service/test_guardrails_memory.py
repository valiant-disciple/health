"""
Tests for the full guardrail + memory stack.
L1  — Presidio PHI redaction + OpenAI Moderation
L2  — NeMo dialog rails
L3  — same as L1 on output
L4  — deterministic critical value thresholds
Mem — Graphiti / Mem0 init and public API smoke tests
"""
import asyncio
import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

# Load .env so config.py settings resolve
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


# ─── L1: Presidio ────────────────────────────────────────────────────────────

def test_presidio_initializes():
    from services.guardrails import _get_presidio
    analyzer, anonymizer = _get_presidio()
    assert analyzer is not None
    assert anonymizer is not None


def test_presidio_redacts_ssn():
    from services.guardrails import _presidio_scan
    text = "My SSN is 078-05-1120 and I have high glucose."
    result, _ = _presidio_scan(text)
    assert "078-05-1120" not in result
    assert "glucose" in result  # health content preserved


def test_presidio_redacts_email():
    from services.guardrails import _presidio_scan
    text = "Please send results to patient@example.com"
    result, _ = _presidio_scan(text)
    assert "patient@example.com" not in result


def test_presidio_clean_text_passes_through():
    from services.guardrails import _presidio_scan
    text = "My hemoglobin is 14.2 g/dL which is within normal range."
    result, is_safe = _presidio_scan(text)
    assert is_safe is True
    assert "hemoglobin" in result


# ─── L1: OpenAI Moderation (mocked — don't call real API in unit tests) ──────

def _make_mock_moderation_client(flagged: bool, categories: dict):
    """Build a mock AsyncOpenAI client that returns a moderation response."""
    mock_result = MagicMock()
    mock_result.flagged = flagged
    mock_result.categories = MagicMock()
    mock_result.categories.__dict__ = categories
    mock_response = MagicMock()
    mock_response.results = [mock_result]

    instance = AsyncMock()
    instance.moderations.create = AsyncMock(return_value=mock_response)
    mock_cls = MagicMock(return_value=instance)
    return mock_cls


@pytest.mark.asyncio
async def test_openai_moderation_passes_safe_text():
    mock_cls = _make_mock_moderation_client(flagged=False, categories={})
    with patch("openai.AsyncOpenAI", mock_cls):
        from services.guardrails import _openai_moderation
        is_safe = await _openai_moderation("My cholesterol is 210 mg/dL.")
        assert is_safe is True


@pytest.mark.asyncio
async def test_openai_moderation_blocks_harmful():
    mock_cls = _make_mock_moderation_client(flagged=True, categories={"self_harm": True})
    with patch("openai.AsyncOpenAI", mock_cls):
        from services.guardrails import _openai_moderation
        is_safe = await _openai_moderation("harmful content here")
        assert is_safe is False


@pytest.mark.asyncio
async def test_scan_user_input_redacts_and_moderates():
    mock_cls = _make_mock_moderation_client(flagged=False, categories={})
    with patch("openai.AsyncOpenAI", mock_cls):
        from services.guardrails import scan_user_input
        sanitized, is_allowed = await scan_user_input(
            "My SSN is 078-05-1120. What does my HbA1c of 6.2 mean?"
        )
        assert "078-05-1120" not in sanitized
        assert is_allowed is True


# ─── L2: NeMo dialog rails ────────────────────────────────────────────────────

def test_nemo_config_exists():
    config_path = os.path.join(os.path.dirname(__file__), "nemo_config")
    assert os.path.isdir(config_path), "nemo_config/ directory missing"
    assert os.path.isfile(os.path.join(config_path, "config.yml"))
    assert os.path.isfile(os.path.join(config_path, "rails.co"))


def test_nemo_config_yml_valid():
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "nemo_config", "config.yml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    assert "models" in config
    assert "rails" in config
    assert config["rails"]["input"]["flows"]
    assert config["rails"]["output"]["flows"]


def test_nemo_rails_co_contains_crisis_flow():
    rails_path = os.path.join(os.path.dirname(__file__), "nemo_config", "rails.co")
    with open(rails_path) as f:
        content = f.read()
    assert "check crisis" in content
    assert "911" in content or "emergency" in content
    assert "check prescribe request" in content
    assert "check off topic" in content


@pytest.mark.asyncio
async def test_apply_dialog_rails_passthrough_when_no_config(tmp_path):
    """When nemo_config doesn't exist, apply_dialog_rails passes through."""
    import services.guardrails as g
    original = g._nemo_rails
    g._nemo_rails = None  # reset singleton

    with patch("services.guardrails.os.path.isdir", return_value=False):
        from services.guardrails import apply_dialog_rails
        msg, allowed = await apply_dialog_rails("What does my glucose level mean?")
        assert allowed is True
        assert msg == "What does my glucose level mean?"

    g._nemo_rails = original


@pytest.mark.asyncio
async def test_apply_dialog_rails_blocks_crisis():
    """NeMo should block crisis messages and return emergency redirect."""
    mock_rails = AsyncMock()
    mock_rails.generate_async = AsyncMock(
        return_value="I'm really concerned. Please call 911 or 988 immediately."
    )

    import services.guardrails as g
    original = g._nemo_rails
    g._nemo_rails = mock_rails

    from services.guardrails import apply_dialog_rails
    response, allowed = await apply_dialog_rails("I want to hurt myself")
    assert allowed is False
    assert "911" in response or "988" in response or "emergency" in response.lower()

    g._nemo_rails = original


@pytest.mark.asyncio
async def test_apply_dialog_rails_allows_health_query():
    """NeMo should allow legitimate health questions."""
    mock_rails = AsyncMock()
    mock_rails.generate_async = AsyncMock(
        return_value="What does my glucose level mean?"  # NeMo echoes the message when allowed
    )

    import services.guardrails as g
    original = g._nemo_rails
    g._nemo_rails = mock_rails

    from services.guardrails import apply_dialog_rails
    _, allowed = await apply_dialog_rails("What does my glucose level mean?")
    assert allowed is True

    g._nemo_rails = original


# ─── L4: Critical value thresholds ───────────────────────────────────────────

from services.guardrails import check_critical_values

def test_critical_glucose_high():
    results = [{"loinc_code": "2339-0", "value_numeric": 520, "unit": "mg/dL", "biomarker_name": "Glucose"}]
    flags = check_critical_values(results)
    assert len(flags) == 1
    assert flags[0]["alert"] == "critical_high"
    assert flags[0]["urgency"] == "urgent"


def test_critical_glucose_low():
    results = [{"loinc_code": "2339-0", "value_numeric": 35, "unit": "mg/dL", "biomarker_name": "Glucose"}]
    flags = check_critical_values(results)
    assert len(flags) == 1
    assert flags[0]["alert"] == "critical_low"


def test_critical_hemoglobin_low():
    results = [{"loinc_code": "718-7", "value_numeric": 6.5, "unit": "g/dL", "biomarker_name": "Hemoglobin"}]
    flags = check_critical_values(results)
    assert len(flags) == 1
    assert flags[0]["alert"] == "critical_low"


def test_normal_values_not_flagged():
    results = [
        {"loinc_code": "2339-0", "value_numeric": 95, "unit": "mg/dL", "biomarker_name": "Glucose"},
        {"loinc_code": "718-7",  "value_numeric": 14.2, "unit": "g/dL", "biomarker_name": "Hemoglobin"},
    ]
    flags = check_critical_values(results)
    assert flags == []


def test_unknown_loinc_not_flagged():
    results = [{"loinc_code": "9999-9", "value_numeric": 99999, "unit": "U/L"}]
    assert check_critical_values(results) == []


def test_multiple_critical_values():
    results = [
        {"loinc_code": "2823-3", "value_numeric": 7.0, "unit": "mEq/L", "biomarker_name": "Potassium"},
        {"loinc_code": "2951-2", "value_numeric": 170, "unit": "mEq/L", "biomarker_name": "Sodium"},
    ]
    flags = check_critical_values(results)
    assert len(flags) == 2
    alerts = {f["alert"] for f in flags}
    assert "critical_high" in alerts


# ─── Full run_guardrails pipeline ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_guardrails_clean():
    mock_cls = _make_mock_moderation_client(flagged=False, categories={})
    with patch("openai.AsyncOpenAI", mock_cls):
        from services.guardrails import run_guardrails
        output, is_safe, critical = await run_guardrails(
            user_input="What is my HbA1c?",
            llm_output="Your HbA1c of 5.8% is at the low end of the prediabetes range.",
            lab_results=[{"loinc_code": "4548-4", "value_numeric": 5.8, "unit": "%", "biomarker_name": "HbA1c"}],
        )
        assert is_safe is True
        assert critical == []


@pytest.mark.asyncio
async def test_run_guardrails_catches_critical():
    mock_cls = _make_mock_moderation_client(flagged=False, categories={})
    with patch("openai.AsyncOpenAI", mock_cls):
        from services.guardrails import run_guardrails
        _, _, critical = await run_guardrails(
            user_input="check my glucose",
            llm_output="Your glucose is very high.",
            lab_results=[{"loinc_code": "2339-0", "value_numeric": 600, "unit": "mg/dL", "biomarker_name": "Glucose"}],
        )
        assert len(critical) == 1
        assert critical[0]["urgency"] == "urgent"


# ─── Memory service smoke tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graphiti_init_with_bad_creds_logs_error():
    """Bad Neo4j creds should log error and not raise."""
    import services.memory as m
    original = m._graphiti
    m._graphiti = None

    with patch("services.memory.settings") as mock_settings:
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.PRIMARY_MODEL = "gpt-4o"
        mock_settings.NEO4J_URI = "neo4j+s://invalid.example.com"
        mock_settings.NEO4J_USER = "neo4j"
        mock_settings.NEO4J_PASSWORD = "wrong"

        # Should not raise — must degrade gracefully
        await m.init_graphiti()

    m._graphiti = original


@pytest.mark.asyncio
async def test_store_health_episode_noop_when_not_initialized():
    import services.memory as m
    original = m._graphiti
    m._graphiti = None

    # Must not raise
    await m.store_health_episode("user-123", {
        "event_type": "lab_result",
        "occurred_at": "2025-01-01T00:00:00Z",
        "biomarker_name": "Glucose",
        "biomarker_code": "2339-0",
        "value_numeric": 95,
        "unit": "mg/dL",
        "status": "normal",
    })

    m._graphiti = original


@pytest.mark.asyncio
async def test_extract_and_store_facts_noop_when_not_initialized():
    import services.memory as m
    original = m._graphiti
    m._graphiti = None

    interpretation = {
        "key_findings": [{"name": "Glucose", "loinc": "2339-0", "value": "95 mg/dL", "status": "normal", "explanation": "Normal."}],
        "dietary_suggestions": [],
    }
    await m.extract_and_store_facts("user-123", interpretation, "report-456")

    m._graphiti = original


@pytest.mark.asyncio
async def test_get_relevant_memories_returns_empty_when_not_initialized():
    import services.memory as m
    original = m._mem0
    m._mem0 = None

    # Without mem0, must return empty string
    result = await m.get_relevant_memories("user-123", "glucose levels")
    assert result == ""

    m._mem0 = original


@pytest.mark.asyncio
async def test_get_relevant_memories_with_mock_mem0():
    import services.memory as m
    original = m._mem0

    mock_mem0 = MagicMock()
    mock_mem0.search = MagicMock(return_value={
        "results": [
            {"memory": "User has a history of elevated glucose."},
            {"memory": "User takes metformin 500mg twice daily."},
        ]
    })
    m._mem0 = mock_mem0

    result = await m.get_relevant_memories("user-123", "glucose", limit=2)
    assert "elevated glucose" in result
    assert "metformin" in result

    m._mem0 = original


@pytest.mark.asyncio
async def test_update_user_memory_with_mock_mem0():
    import services.memory as m
    original = m._mem0

    mock_mem0 = MagicMock()
    mock_mem0.add = MagicMock(return_value={"results": []})
    m._mem0 = mock_mem0

    messages = [
        {"role": "user", "content": "What does my HbA1c mean?"},
        {"role": "assistant", "content": "Your HbA1c of 5.8% is in the prediabetes range."},
    ]
    await m.update_user_memory("user-123", messages)
    mock_mem0.add.assert_called_once_with(messages, user_id="user-123", metadata=None)

    m._mem0 = original


# ─── NeMo config loads cleanly ────────────────────────────────────────────────

def test_nemo_rails_config_loads():
    """Verify NeMo can parse the config without error."""
    import warnings
    config_path = os.path.join(os.path.dirname(__file__), "nemo_config")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from nemoguardrails import RailsConfig
        config = RailsConfig.from_path(config_path)
    assert config is not None
