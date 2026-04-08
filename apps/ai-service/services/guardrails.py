"""
4-layer guardrail stack:
  L1 — LLM Guard input scan
  L2 — NeMo Guardrails (dialog rails) — wraps LLM calls in chat router
  L3 — LLM Guard output scan
  L4 — Deterministic critical lab threshold check
"""
from __future__ import annotations
import structlog

log = structlog.get_logger()

# Critical lab thresholds (LOINC code → {critical_high, critical_low})
CRITICAL_THRESHOLDS: dict[str, dict] = {
    "2339-0":  {"critical_high": 500,   "critical_low": 40},    # Glucose mg/dL
    "4548-4":  {"critical_high": 10.0},                          # HbA1c %
    "2160-0":  {"critical_high": 10.0},                          # Creatinine mg/dL
    "718-7":   {"critical_low":  7.0},                           # Hemoglobin g/dL
    "2823-3":  {"critical_high": 6.5,   "critical_low": 2.5},    # Potassium mEq/L
    "2951-2":  {"critical_high": 160,   "critical_low": 120},    # Sodium mEq/L
    "6690-2":  {"critical_high": 30000, "critical_low": 2000},   # WBC /µL
    "777-3":   {"critical_low": 50000},                          # Platelets /µL
    "1920-8":  {"critical_high": 1000},                          # AST U/L
    "2324-2":  {"critical_high": 1000},                          # ALT U/L
}


async def scan_user_input(user_message: str) -> tuple[str, bool]:
    """L1 — Scan user input with LLM Guard before sending to LLM."""
    try:
        from llm_guard import scan_prompt
        from llm_guard.input_scanners import PromptInjection, Toxicity, BanTopics

        scanners = [
            PromptInjection(threshold=0.85),
            Toxicity(threshold=0.80),
            BanTopics(
                topics=["self-harm", "suicide"],
                threshold=0.75,
            ),
        ]
        sanitized, results, is_valid = scan_prompt(scanners, user_message)
        if not is_valid:
            violated = [k for k, v in results.items() if not v.is_valid]
            log.warning("input_scan.blocked", violated=violated)
        return sanitized, is_valid
    except Exception as e:
        # Guardrail errors should NOT block the request — log and pass through
        log.error("input_scan.error", error=str(e))
        return user_message, True


async def scan_llm_output(prompt: str, output: str) -> tuple[str, bool]:
    """L3 — Scan LLM output with LLM Guard."""
    try:
        from llm_guard import scan_output
        from llm_guard.output_scanners import Toxicity, BanTopics, Sensitive

        scanners = [
            Toxicity(threshold=0.80),
            Sensitive(redact=False, threshold=0.85),
            BanTopics(
                topics=["diagnosis", "prescribe"],
                threshold=0.70,
            ),
        ]
        sanitized, results, is_valid = scan_output(scanners, prompt, output)
        if not is_valid:
            violated = [k for k, v in results.items() if not v.is_valid]
            log.warning("output_scan.blocked", violated=violated)
        return sanitized, is_valid
    except Exception as e:
        log.error("output_scan.error", error=str(e))
        return output, True


def check_critical_values(lab_results: list) -> list[dict]:
    """L4 — Deterministic: flag lab values beyond hard safety thresholds."""
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
                "alert": "critical_high",
                "urgency": "urgent",
                "message": f"{name} critically elevated at {v} {unit}. Please seek care today.",
            })
        elif thresh.get("critical_low") and float(v) <= thresh["critical_low"]:
            critical.append({
                **r,
                "alert": "critical_low",
                "urgency": "urgent",
                "message": f"{name} critically low at {v} {unit}. Please seek care today.",
            })
    return critical


async def run_guardrails(
    user_input: str,
    llm_output: str,
    lab_results: list | None = None,
) -> tuple[str, bool, list]:
    """
    Full guardrail pipeline.
    Returns: (safe_output, is_safe, critical_flags)
    """
    # L3 output scan
    safe_output, output_safe = await scan_llm_output(user_input, llm_output)

    # L4 critical values
    critical = check_critical_values(lab_results or [])

    return safe_output, output_safe, critical
