"""
4-layer guardrail stack
  L1 — Presidio input scan (PHI/PII detection) + OpenAI Moderation API
  L2 — NeMo Guardrails (dialog rails) — topic gating, crisis routing
  L3 — Presidio output scan + OpenAI Moderation API
  L4 — Deterministic critical lab threshold check

All layers degrade gracefully: if a service is unavailable the request
passes through with a warning log rather than failing the user.
"""
from __future__ import annotations
import os
import structlog

log = structlog.get_logger()

# ─── Critical lab thresholds (LOINC → {critical_high, critical_low}) ─────────

CRITICAL_THRESHOLDS: dict[str, dict] = {
    "2339-0": {"critical_high": 500,   "critical_low": 40},    # Glucose mg/dL
    "4548-4": {"critical_high": 10.0},                          # HbA1c %
    "2160-0": {"critical_high": 10.0},                          # Creatinine mg/dL
    "718-7":  {"critical_low":  7.0},                           # Hemoglobin g/dL
    "2823-3": {"critical_high": 6.5,   "critical_low": 2.5},    # Potassium mEq/L
    "2951-2": {"critical_high": 160,   "critical_low": 120},    # Sodium mEq/L
    "6690-2": {"critical_high": 30000, "critical_low": 2000},   # WBC /µL
    "777-3":  {"critical_low": 50000},                          # Platelets /µL
    "1920-8": {"critical_high": 1000},                          # AST U/L
    "2324-2": {"critical_high": 1000},                          # ALT U/L
}

# ─── Presidio setup (lazy singleton) ─────────────────────────────────────────

_analyzer = None
_anonymizer = None


def _get_presidio():
    global _analyzer, _anonymizer
    if _analyzer is not None:
        return _analyzer, _anonymizer
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        # Use spaCy en_core_web_sm — bundled with presidio
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        })
        _analyzer  = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        _anonymizer = AnonymizerEngine()
        log.info("presidio.initialized")
    except Exception as e:
        log.error("presidio.init_failed", error=str(e), exc_info=True)
    return _analyzer, _anonymizer


def _presidio_scan(text: str) -> tuple[str, bool]:
    """Run Presidio PHI/PII analysis. Returns (possibly-redacted text, is_safe)."""
    analyzer, anonymizer = _get_presidio()
    if not analyzer:
        return text, True
    try:
        results = analyzer.analyze(text=text, language="en")
        # PHI entities that warrant flagging
        blocked_types = {"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "MEDICAL_LICENSE"}
        flagged = [r for r in results if r.entity_type in blocked_types]
        if flagged:
            # Anonymize in-place rather than reject — keeps UX smooth
            anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
            log.info("presidio.redacted", entity_types=[r.entity_type for r in flagged])
            return anonymized.text, True
        return text, True
    except Exception as e:
        log.error("presidio.scan_failed", error=str(e), exc_info=True)
        return text, True


async def _openai_moderation(text: str) -> bool:
    """OpenAI Moderation API — free, fast, catches self-harm / violence."""
    try:
        from openai import AsyncOpenAI
        from config import settings
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.moderations.create(
            model="omni-moderation-latest",
            input=text,
        )
        result = response.results[0]
        if result.flagged:
            cats = {k for k, v in result.categories.__dict__.items() if v}
            log.warning("openai_moderation.flagged", categories=list(cats))
            return False
        return True
    except Exception as e:
        log.error("openai_moderation.failed", error=str(e), exc_info=True)
        return True  # degrade to passthrough


async def scan_user_input(user_message: str) -> tuple[str, bool]:
    """
    L1 — Scan user input.
    1. Presidio: redact PHI before it reaches the LLM
    2. OpenAI Moderation: block self-harm / violence content
    Returns (sanitized_text, is_allowed).
    """
    sanitized, _ = _presidio_scan(user_message)
    is_safe = await _openai_moderation(sanitized)
    return sanitized, is_safe


async def scan_llm_output(prompt: str, output: str) -> tuple[str, bool]:
    """
    L3 — Scan LLM output.
    1. Presidio: catch any PHI the model may have leaked
    2. OpenAI Moderation: block harmful output
    Returns (sanitized_output, is_allowed).
    """
    sanitized, _ = _presidio_scan(output)
    is_safe = await _openai_moderation(sanitized)
    return sanitized, is_safe


# ─── NeMo L2 (dialog rails) ──────────────────────────────────────────────────

_nemo_rails = None


def _get_nemo_rails():
    global _nemo_rails
    if _nemo_rails is not None:
        return _nemo_rails
    try:
        from nemoguardrails import RailsConfig, LLMRails
        config_path = os.path.join(os.path.dirname(__file__), "..", "nemo_config")
        if os.path.isdir(config_path):
            config = RailsConfig.from_path(config_path)
            _nemo_rails = LLMRails(config)
            log.info("nemo.initialized")
        else:
            log.warning("nemo.config_not_found", path=config_path)
    except Exception as e:
        log.error("nemo.init_failed", error=str(e), exc_info=True)
    return _nemo_rails


async def apply_dialog_rails(user_message: str) -> tuple[str, bool]:
    """
    L2 — NeMo dialog rails.
    Blocks: off-topic requests, crisis situations (routes to emergency services),
    requests for prescriptions or diagnoses.
    Returns (response_or_original, is_allowed). Degrades to passthrough if unavailable.
    """
    rails = _get_nemo_rails()
    if not rails:
        return user_message, True
    try:
        response = await rails.generate_async(
            messages=[{"role": "user", "content": user_message}]
        )
        # NeMo returns its own refusal message when a rail fires
        refusal_signals = [
            "i'm sorry, i can't",
            "cannot help with that",
            "please call 911",
            "please call emergency",
            "i'm not able to",
        ]
        content = (response or "").lower()
        if any(sig in content for sig in refusal_signals):
            log.warning("nemo.dialog_blocked", snippet=content[:120])
            return response, False
        return user_message, True
    except Exception as e:
        log.error("nemo.apply_failed", error=str(e), exc_info=True)
        return user_message, True


# ─── L4 — Deterministic critical value check ─────────────────────────────────

def check_critical_values(lab_results: list) -> list[dict]:
    """L4 — Flag lab values beyond hard safety thresholds."""
    critical = []
    for r in lab_results:
        thresh = CRITICAL_THRESHOLDS.get(r.get("loinc_code") or r.get("biomarker_code", ""))
        if not thresh:
            continue
        v = r.get("value_numeric")
        if v is None:
            continue
        name = r.get("biomarker_name", r.get("loinc_code", "Unknown"))
        unit = r.get("unit", "")
        if thresh.get("critical_high") and float(v) >= thresh["critical_high"]:
            critical.append({
                **r,
                "alert":   "critical_high",
                "urgency": "urgent",
                "message": f"{name} critically elevated at {v} {unit}. Please seek care today.",
            })
        elif thresh.get("critical_low") and float(v) <= thresh["critical_low"]:
            critical.append({
                **r,
                "alert":   "critical_low",
                "urgency": "urgent",
                "message": f"{name} critically low at {v} {unit}. Please seek care today.",
            })
    return critical


# ─── Full pipeline ────────────────────────────────────────────────────────────

async def run_guardrails(
    user_input: str,
    llm_output: str,
    lab_results: list | None = None,
) -> tuple[str, bool, list]:
    """
    Run L3 + L4 on LLM output (L1 + L2 are applied earlier in the request path).
    Returns: (safe_output, is_safe, critical_flags)
    """
    safe_output, output_safe = await scan_llm_output(user_input, llm_output)
    critical = check_critical_values(lab_results or [])
    return safe_output, output_safe, critical
