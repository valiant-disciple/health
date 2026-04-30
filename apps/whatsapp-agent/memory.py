"""Memory + context builder.

For every user turn, the orchestrator needs to know:
  - The user's recent conversation (rolling window or summary + window)
  - Structured facts we've learned (symptoms, conditions, lifestyle)
  - Their lab history (recent biomarker values)
  - Previous explanations we've given (so we can say "remember when I told you...")

This module assembles all that into a single context block.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog

from config import get_settings
from db import execute, fetch_all, fetch_one, fetch_val
from llm import json_chat

log = structlog.get_logger()


# ── Conversation history ─────────────────────────────────────────────────


async def recent_conversation(user_id: UUID, limit: int | None = None) -> list[dict[str, Any]]:
    """Return last N messages, oldest-first, ready for LLM `messages` array."""
    n = limit or get_settings().conversation_history_turns
    rows = await fetch_all(
        """
        SELECT role, content, msg_type, created_at
          FROM conversations
         WHERE user_id = $1
         ORDER BY created_at DESC
         LIMIT $2
        """,
        user_id,
        n,
    )
    return list(reversed(rows))


async def append_conversation(
    user_id: UUID,
    role: str,
    content: str,
    *,
    msg_type: str = "text",
    twilio_sid: str | None = None,
    extracted_entities: dict | None = None,
    prompt_version: str | None = None,
    model_used: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> UUID:
    rec = await fetch_one(
        """
        INSERT INTO conversations
          (user_id, role, content, msg_type, twilio_sid, extracted_entities,
           prompt_version, model_used, tokens_in, tokens_out, cost_usd)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        user_id, role, content, msg_type, twilio_sid, extracted_entities or {},
        prompt_version, model_used, tokens_in, tokens_out, cost_usd,
    )
    return rec["id"]


# ── User facts ────────────────────────────────────────────────────────────


async def get_active_facts(user_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
    return await fetch_all(
        """
        SELECT fact_type, fact_key, fact_value, confidence, learned_at
          FROM user_facts
         WHERE user_id = $1 AND superseded_at IS NULL
         ORDER BY confidence DESC, learned_at DESC
         LIMIT $2
        """,
        user_id,
        limit,
    )


async def upsert_fact(
    user_id: UUID,
    fact_type: str,
    fact_key: str,
    fact_value: str,
    *,
    source_conversation_id: UUID | None = None,
    confidence: float = 0.8,
) -> None:
    """If a fact with the same (user_id, fact_type, fact_key) exists, supersede it."""
    await execute(
        """
        UPDATE user_facts
           SET superseded_at = now()
         WHERE user_id = $1 AND fact_type = $2 AND fact_key = $3 AND superseded_at IS NULL
        """,
        user_id, fact_type, fact_key,
    )
    await execute(
        """
        INSERT INTO user_facts
          (user_id, fact_type, fact_key, fact_value, source_conversation_id, confidence)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id, fact_type, fact_key, fact_value, source_conversation_id, confidence,
    )


# ── Lab history ──────────────────────────────────────────────────────────


async def recent_lab_results(user_id: UUID, days: int | None = None) -> list[dict[str, Any]]:
    n_days = days or get_settings().lab_history_days
    return await fetch_all(
        """
        SELECT loinc_code, test_name_normalized, value, unit, ref_range_text,
               status, measured_at, tier
          FROM biomarker_results
         WHERE user_id = $1
           AND measured_at IS NOT NULL
           AND measured_at >= current_date - make_interval(days => $2)
         ORDER BY measured_at DESC, loinc_code
        """,
        user_id,
        n_days,
    )


async def previous_explanation(
    user_id: UUID, loinc_code: str | None
) -> dict[str, Any] | None:
    if not loinc_code:
        return None
    return await fetch_one(
        """
        SELECT explanation_text, created_at
          FROM report_biomarker_explanations
         WHERE user_id = $1 AND loinc_code = $2
         ORDER BY created_at DESC
         LIMIT 1
        """,
        user_id, loinc_code,
    )


async def all_previous_explanations(user_id: UUID, limit: int = 30) -> list[dict[str, Any]]:
    return await fetch_all(
        """
        SELECT loinc_code, explanation_text, created_at
          FROM report_biomarker_explanations
         WHERE user_id = $1
         ORDER BY created_at DESC
         LIMIT $2
        """,
        user_id, limit,
    )


# ── Context assembly for the orchestrator ────────────────────────────────


async def build_user_context_block(user_id: UUID, current_message: str = "") -> str:
    """Build a compact prose block of user state. Goes into system prompt."""
    s = get_settings()

    user = await fetch_one(
        "SELECT conversation_summary, total_messages, total_reports FROM users WHERE id = $1",
        user_id,
    )
    summary = (user or {}).get("conversation_summary") or ""

    facts = await get_active_facts(user_id, limit=15)
    labs = await recent_lab_results(user_id, days=s.lab_history_days)
    prior = await all_previous_explanations(user_id, limit=15)

    parts: list[str] = []

    if summary:
        parts.append(f"## Long-term context\n{summary}")

    if facts:
        fact_lines = [f"- {f['fact_type']}: {f['fact_key']} = {f['fact_value']}" for f in facts]
        parts.append("## What we know about this user\n" + "\n".join(fact_lines))

    if labs:
        # Group by date (most recent first)
        by_date: dict[str, list[dict]] = {}
        for r in labs:
            d = (r["measured_at"] or "").isoformat() if r.get("measured_at") else "unknown"
            by_date.setdefault(d, []).append(r)
        lab_lines = ["## Lab history (most recent first)"]
        for d, rows in list(by_date.items())[:6]:  # last 6 reports
            lab_lines.append(f"\nDate: {d}")
            for r in rows[:25]:
                v = r.get("value") if r.get("value") is not None else "-"
                u = r.get("unit") or ""
                rng = r.get("ref_range_text") or ""
                st = r.get("status") or ""
                name = r.get("test_name_normalized") or r.get("loinc_code") or "?"
                lab_lines.append(f"  {name}: {v} {u} (ref: {rng}) [{st}]")
        parts.append("\n".join(lab_lines))

    if prior:
        prior_lines = ["## Previous explanations we've given (do not repeat verbatim, but recall and reference)"]
        for p in prior[:8]:
            t = p["explanation_text"][:300]
            prior_lines.append(f"- {p['loinc_code']}: {t}")
        parts.append("\n".join(prior_lines))

    return "\n\n".join(parts) if parts else "(no prior interactions yet)"


# ── Fact extraction (run after each turn) ────────────────────────────────

FACT_EXTRACTION_PROMPT = """\
You are extracting durable facts about a user from the latest exchange below.

Extract only facts that should persist across future conversations. Examples:
  - symptoms the user reports ("feels fatigued", "has headaches")
  - conditions they mention ("has hypertension", "diagnosed with PCOS")
  - medications ("on metformin", "takes vitamin D supplement")
  - lifestyle ("vegetarian", "drinks alcohol weekly", "exercises 3x/week")
  - demographics ("35 year old male", "lives in Mumbai")
  - preferences ("prefers concise answers", "wants Hindi responses")

Do NOT extract:
  - One-off questions
  - Lab values (those are in a separate table)
  - Things the user negates ("I don't smoke" → don't extract)

Return JSON:
{
  "facts": [
    {
      "fact_type": "symptom|condition|medication|lifestyle|preference|demographic",
      "fact_key":  "short snake_case key",
      "fact_value": "value or 'yes'",
      "confidence": 0.0-1.0
    }
  ]
}
If nothing useful, return {"facts": []}. JSON only.
"""


async def extract_and_store_facts(
    user_id: UUID,
    user_msg: str,
    assistant_msg: str,
    source_conversation_id: UUID | None = None,
    user_hash: str | None = None,
) -> list[dict]:
    """Run a small JSON LLM call to extract facts, persist them. Best-effort."""
    if not user_msg.strip():
        return []
    try:
        parsed, _ = await json_chat(
            messages=[
                {"role": "system", "content": FACT_EXTRACTION_PROMPT},
                {"role": "user", "content": f"USER: {user_msg}\n\nASSISTANT: {assistant_msg[:1500]}"},
            ],
            model=get_settings().extractor_model,
            max_tokens=400,
            user_hash=user_hash,
        )
    except Exception as e:
        log.warning("memory.fact_extract_failed", error=str(e))
        return []

    facts = parsed.get("facts") or []
    out: list[dict] = []
    for f in facts:
        try:
            await upsert_fact(
                user_id=user_id,
                fact_type=f.get("fact_type", "preference"),
                fact_key=f.get("fact_key", "")[:80],
                fact_value=str(f.get("fact_value", ""))[:200],
                source_conversation_id=source_conversation_id,
                confidence=float(f.get("confidence", 0.7)),
            )
            out.append(f)
        except Exception as e:
            log.warning("memory.fact_store_failed", fact=f, error=str(e))
    if out:
        log.info("memory.facts_stored", n=len(out))
    return out


# ── Conversation summarisation ───────────────────────────────────────────

SUMMARY_PROMPT = """\
You are condensing a long conversation between a user and a health assistant
into a stable summary the assistant can carry forward indefinitely.

Capture:
  - The user's situation and key concerns
  - Prior reports / biomarker findings
  - Major topics already discussed (and how the assistant explained them)
  - Anything the user asked the assistant to remember

Be concise (max 200 words). Write in third person ("the user").
"""


async def maybe_update_summary(user_id: UUID, user_hash: str | None = None) -> None:
    """If conversation > threshold, regenerate the rolling summary."""
    s = get_settings()
    n = await fetch_val(
        "SELECT count(*) FROM conversations WHERE user_id = $1",
        user_id,
    )
    if (n or 0) < s.conversation_summary_threshold:
        return

    # Pull a wider window for the summarisation, oldest first
    rows = await fetch_all(
        """
        SELECT role, content FROM conversations
         WHERE user_id = $1
         ORDER BY created_at ASC
         LIMIT 200
        """,
        user_id,
    )
    if not rows:
        return

    transcript = "\n".join(f"{r['role'].upper()}: {r['content']}" for r in rows)
    try:
        result, _ = await json_chat(
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT + "\nReturn JSON: {\"summary\": \"...\"}"},
                {"role": "user", "content": transcript[:25000]},
            ],
            model=s.extractor_model,
            max_tokens=500,
            user_hash=user_hash,
        )
        summary = (result or {}).get("summary", "").strip()
        if summary:
            await execute(
                "UPDATE users SET conversation_summary = $2 WHERE id = $1",
                user_id, summary,
            )
            log.info("memory.summary_updated", user_id=str(user_id)[:8], chars=len(summary))
    except Exception as e:
        log.warning("memory.summary_failed", error=str(e))
