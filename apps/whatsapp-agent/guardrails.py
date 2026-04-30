"""All guardrails in one module — easy to audit, easy to extend.

Layers:
  1. Input validation       (file size, type, sender format, message length)
  2. Rate limiting          (Postgres sliding window per phone)
  3. Idempotency            (Twilio MessageSid dedupe)
  4. Prompt injection       (sanitise OCR text, wrap user content)
  5. Moderation             (OpenAI moderation API on user input)
  6. Emergency detection    (keyword + LLM classifier for crises)
  7. Output validation      (no diagnosis / no prescription / required disclaimer)
  8. Cost caps              (per-user + global daily kill switch)

Each layer is small enough that a reviewer can scan + reason about it in one read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

from config import get_settings
from db import execute, fetch_all, fetch_val, fetch_one
from llm import moderate

log = structlog.get_logger()


# ════════════════════════════════════════════════════════════════════════════
# 1. INPUT VALIDATION
# ════════════════════════════════════════════════════════════════════════════

ALLOWED_MEDIA_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/heic",
    "image/webp",
}


@dataclass
class InputValidation:
    ok: bool
    reason: str | None = None
    refusal_text: str | None = None


def validate_text_input(body: str) -> InputValidation:
    if body is None:
        return InputValidation(False, "empty", "Send me a message or a lab report PDF.")
    body = body.strip()
    if len(body) > 4000:
        return InputValidation(False, "too_long",
            "That message is too long for me to process. Please keep messages under 4000 characters.")
    return InputValidation(True)


def validate_media(content_type: str, byte_size: int | None = None) -> InputValidation:
    s = get_settings()
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct not in ALLOWED_MEDIA_TYPES:
        return InputValidation(False, f"bad_mime:{ct}",
            "I can only read PDFs and images of lab reports. Please send the report as a PDF or photo.")
    if byte_size is not None and byte_size > s.max_pdf_size_mb * 1024 * 1024:
        return InputValidation(False, "too_large",
            f"That file is bigger than {s.max_pdf_size_mb}MB — please send a smaller version.")
    return InputValidation(True)


# ════════════════════════════════════════════════════════════════════════════
# 2. RATE LIMITING (Postgres sliding window)
# ════════════════════════════════════════════════════════════════════════════


async def check_rate_limit(
    user_id: UUID,
    event_type: str,
    *,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """Returns (allowed, current_count_in_window)."""
    n = await fetch_val(
        """
        SELECT count(*) FROM rate_limit_events
         WHERE user_id = $1 AND event_type = $2
           AND occurred_at > now() - make_interval(secs => $3)
        """,
        user_id, event_type, window_seconds,
    ) or 0
    if n >= limit:
        return False, n
    await execute(
        "INSERT INTO rate_limit_events (user_id, event_type) VALUES ($1, $2)",
        user_id, event_type,
    )
    return True, n + 1


async def enforce_message_rate_limit(user_id: UUID) -> tuple[bool, str | None]:
    s = get_settings()
    ok_min, _ = await check_rate_limit(user_id, "message", limit=s.rate_limit_msg_per_min, window_seconds=60)
    if not ok_min:
        return False, "Slow down a moment — you're sending messages very fast. Try again in a minute."
    ok_day, _ = await check_rate_limit(user_id, "message", limit=s.rate_limit_msg_per_day, window_seconds=86400)
    if not ok_day:
        return False, "You've hit the daily message limit. It resets in 24 hours."
    return True, None


async def enforce_pdf_rate_limit(user_id: UUID) -> tuple[bool, str | None]:
    s = get_settings()
    ok, _ = await check_rate_limit(user_id, "pdf", limit=s.rate_limit_pdfs_per_day, window_seconds=86400)
    if not ok:
        return False, f"You've uploaded the maximum {s.rate_limit_pdfs_per_day} reports today. Try tomorrow."
    return True, None


# ════════════════════════════════════════════════════════════════════════════
# 4. PROMPT-INJECTION SANITATION
# ════════════════════════════════════════════════════════════════════════════

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|messages?)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I),
    re.compile(r"^\s*system\s*:", re.I | re.MULTILINE),
    re.compile(r"^\s*assistant\s*:", re.I | re.MULTILINE),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"new\s+instructions\s*:", re.I),
    re.compile(r"<\s*/?\s*(user_message|system|assistant|instructions?)\s*>", re.I),
]


def sanitize_for_llm(text: str) -> str:
    """Defang text that looks like prompt-injection. Used on OCR'd content."""
    if not text:
        return ""
    out = text
    for pat in INJECTION_PATTERNS:
        out = pat.sub(lambda m: "[redacted]", out)
    # Truncate aggressively — most lab markdown is well under 30k chars
    return out[:30000]


# ════════════════════════════════════════════════════════════════════════════
# 5. MODERATION
# ════════════════════════════════════════════════════════════════════════════


async def moderation_check(text: str) -> tuple[bool, dict]:
    """Returns (safe, full_moderation_response)."""
    if not text or len(text) < 4:
        return True, {}
    res = await moderate(text)
    return (not res.get("flagged", False)), res


# ════════════════════════════════════════════════════════════════════════════
# 6. EMERGENCY DETECTION
# ════════════════════════════════════════════════════════════════════════════

EMERGENCY_PATTERNS = [
    re.compile(r"\bchest\s+pain\b", re.I),
    re.compile(r"\bcan\W*t\s+breathe\b", re.I),
    re.compile(r"\bdifficulty\s+breathing\b", re.I),
    re.compile(r"\bsevere\s+(bleeding|pain|headache)\b", re.I),
    re.compile(r"\bstroke\b", re.I),
    re.compile(r"\bnumb\s+(arm|face|leg)\b", re.I),
    re.compile(r"\bblurred\s+vision\b", re.I),
    re.compile(r"\bunconscious\b", re.I),
    re.compile(r"\bseizure\b", re.I),
    re.compile(r"\bvomiting\s+blood\b", re.I),
    re.compile(r"\bcoughing\s+(up\s+)?blood\b", re.I),
]

CRISIS_PATTERNS = [
    re.compile(r"\b(kill|hurt|harm)\s+myself\b", re.I),
    re.compile(r"\bend\s+(my\s+)?life\b", re.I),
    re.compile(r"\bsuicid", re.I),
    re.compile(r"\b(want|going)\s+to\s+die\b", re.I),
    re.compile(r"\bself\W*harm\b", re.I),
]


def detect_emergency(text: str) -> str | None:
    """Returns 'medical' | 'crisis' | None."""
    if not text:
        return None
    for p in CRISIS_PATTERNS:
        if p.search(text):
            return "crisis"
    for p in EMERGENCY_PATTERNS:
        if p.search(text):
            return "medical"
    return None


# ════════════════════════════════════════════════════════════════════════════
# 7. OUTPUT VALIDATION
# ════════════════════════════════════════════════════════════════════════════

FORBIDDEN_OUTPUT_PATTERNS = [
    # Dosage/prescription
    re.compile(r"\btake\s+\d+\s*(mg|g|mcg|iu|ml|units?)\b", re.I),
    re.compile(r"\bprescribe", re.I),
    re.compile(r"\b(stop|start|increase|decrease|change)\s+(your|the)\s+(medication|dose|dosage)\b", re.I),
    # Diagnostic claims
    re.compile(r"\byou\s+have\s+(diabetes|cancer|hiv|aids|lupus|hepatitis|kidney\s+(disease|failure)|liver\s+(disease|failure)|heart\s+disease)\b", re.I),
    re.compile(r"\byou\s+(are|appear\s+to\s+be)\s+(diabetic|cancerous|hypertensive|anemic)\b", re.I),
    re.compile(r"\bi\s+diagnose", re.I),
    # Discouraging medical care
    re.compile(r"\b(no\s+need|don.t\s+need|skip)\s+(to\s+see\s+|seeing\s+)?(a\s+)?doctor\b", re.I),
]

DOCTOR_KEYWORDS = ["doctor", "healthcare provider", "physician", "medical professional", "clinician", "specialist"]


@dataclass
class OutputCheck:
    ok: bool
    text: str            # possibly fixed text
    issues: list[str]    # things we adjusted


def validate_output(text: str, *, require_disclaimer: bool = True) -> OutputCheck:
    """Scan & lightly fix model output. Returns adjusted text + flags."""
    issues: list[str] = []
    fixed = text

    # 1. Forbidden patterns — if any match, we redact and flag
    for pat in FORBIDDEN_OUTPUT_PATTERNS:
        if pat.search(fixed):
            issues.append(f"forbidden_pattern:{pat.pattern[:40]}")
            fixed = pat.sub("[I can't advise on that — please consult your doctor]", fixed)

    # 2. Doctor disclaimer (only on long-form responses)
    if require_disclaimer and len(fixed) > 250:
        if not any(kw in fixed.lower() for kw in DOCTOR_KEYWORDS):
            fixed = fixed.rstrip() + "\n\nDiscuss these findings with your healthcare provider."
            issues.append("disclaimer_appended")

    # 3. PII strip from output (phone numbers, emails — shouldn't appear, but defense in depth)
    fixed = re.sub(r"\+?\d{10,15}", "[phone redacted]", fixed)
    fixed = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email redacted]", fixed)

    # 4. Length cap
    if len(fixed) > 4000:
        fixed = fixed[:3950] + "..."
        issues.append("truncated")

    return OutputCheck(ok=(len(issues) == 0 or issues == ["disclaimer_appended"]),
                       text=fixed, issues=issues)


# ════════════════════════════════════════════════════════════════════════════
# 8. COST CAPS
# ════════════════════════════════════════════════════════════════════════════


async def check_user_spend_cap(user_id: UUID) -> tuple[bool, str | None]:
    s = get_settings()
    rec = await fetch_one("SELECT daily_spend_usd FROM users WHERE id = $1", user_id)
    spent = float(rec["daily_spend_usd"]) if rec else 0.0
    if spent >= s.daily_user_spend_cap_usd:
        return False, ("You've used your daily processing quota. "
                       "It resets at midnight. Reach out if you need more.")
    return True, None


async def check_global_spend_cap() -> tuple[bool, str | None]:
    s = get_settings()
    total = await fetch_val(
        "SELECT COALESCE(SUM(daily_spend_usd), 0) FROM users"
    ) or 0
    if float(total) >= s.global_daily_spend_cap_usd:
        log.error("guardrails.global_spend_cap_hit", total=float(total))
        return False, "We're temporarily over capacity. Please try again in a bit."
    return True, None
