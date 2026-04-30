"""Handlers: business logic for processing each kind of message.

Called from the worker. Each handler:
  - Runs all relevant guardrails
  - Does the actual work (OCR, orchestrator, etc.)
  - Persists results
  - Sends the WhatsApp reply via Twilio REST
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import structlog

from biomarkers import Biomarker, get_registry
from config import get_settings
from crypto import decrypt_pii
from db import (
    add_user_spend,
    audit,
    execute,
    fetch_all,
    fetch_one,
    fetch_val,
    get_pool,
    increment_user_message_count,
    increment_user_pdf_count,
)
from guardrails import (
    detect_emergency,
    enforce_message_rate_limit,
    enforce_pdf_rate_limit,
    moderation_check,
    sanitize_for_llm,
    validate_media,
    validate_output,
    validate_text_input,
    check_user_spend_cap,
    check_global_spend_cap,
)
from llm import json_chat
from memory import (
    append_conversation,
    extract_and_store_facts,
    maybe_update_summary,
)
from ocr import extract_from_image, extract_from_pdf
from orchestrator import respond
from prompts import (
    CRISIS_MENTAL_HEALTH_RESPONSE,
    EMERGENCY_RESPONSE,
    HELP_MESSAGE,
    ONBOARDING_WELCOME,
    REFUSAL_BLOCKED_REPORT,
    REPORT_INTERPRETATION_USER_TEMPLATE,
)
from storage import upload_pdf
from twilio_client import download_media, send_whatsapp

log = structlog.get_logger()


# ════════════════════════════════════════════════════════════════════════════
# TEXT MESSAGE
# ════════════════════════════════════════════════════════════════════════════


async def handle_text(payload: dict[str, Any]) -> None:
    user_id = UUID(payload["user_id"])
    body = payload.get("body", "").strip()
    twilio_sid = payload.get("twilio_sid")
    sender_to = payload.get("sender")  # e.g. "whatsapp:+91..."

    if not body:
        return
    user_hash = await _user_hash_for(user_id)

    # ── 1. Validation ─────────────────────────────────────────────
    v = validate_text_input(body)
    if not v.ok:
        await _reply(sender_to, v.refusal_text or "I couldn't process that.", user_id, msg_type="refusal")
        return

    # ── 2. Rate limit ─────────────────────────────────────────────
    ok, msg = await enforce_message_rate_limit(user_id)
    if not ok:
        await _reply(sender_to, msg or "Rate limit hit.", user_id, msg_type="rate_limit")
        return

    # ── 3. Cost caps ──────────────────────────────────────────────
    ok, cmsg = await check_user_spend_cap(user_id)
    if not ok:
        await _reply(sender_to, cmsg or "Quota reached.", user_id, msg_type="quota")
        return
    ok, gmsg = await check_global_spend_cap()
    if not ok:
        await _reply(sender_to, gmsg or "Capacity issue.", user_id, msg_type="capacity")
        return

    # Persist the inbound message
    inbound_conv_id = await append_conversation(
        user_id=user_id, role="user", content=body, msg_type="text", twilio_sid=twilio_sid
    )

    # ── 4. Emergency / crisis detection ────────────────────────────
    em = detect_emergency(body)
    if em == "crisis":
        await _reply(sender_to, CRISIS_MENTAL_HEALTH_RESPONSE, user_id, msg_type="emergency")
        await audit(user_id, "crisis_response_triggered", {"reason": "self-harm signal"})
        return
    if em == "medical":
        await _reply(sender_to, EMERGENCY_RESPONSE, user_id, msg_type="emergency")
        await audit(user_id, "emergency_response_triggered", {"reason": "medical signal"})
        return

    # ── 5. Pre-consent commands (must work before user agrees) ────
    cmd = body.lower().strip()
    if cmd in ("yes", "i agree", "agree", "i consent"):
        await _maybe_record_consent(user_id)
        await _reply(sender_to,
            "Great — you're all set. Send me a PDF or photo of your lab report whenever you're ready, "
            "or ask any question about a biomarker.", user_id, msg_type="onboarding")
        return
    if cmd in ("delete my data", "delete everything", "wipe my data", "forget me", "stop"):
        await _delete_user_data(user_id)
        await _reply(sender_to,
            "Done — I've deleted all your data. If you ever come back, it'll be a fresh start.",
            user_id, msg_type="dsar")
        return

    # ── 6. Onboarding gate (first-time / unconsented user) ─────────
    user = await fetch_one("SELECT consent_given_at FROM users WHERE id = $1", user_id)
    if not user or not user.get("consent_given_at"):
        await _reply(sender_to, ONBOARDING_WELCOME, user_id, msg_type="onboarding")
        return

    # ── 7. Post-consent commands ──────────────────────────────────
    if cmd in ("help", "?", "menu", "commands"):
        await _reply(sender_to, HELP_MESSAGE, user_id, msg_type="help")
        return
    if cmd in ("list", "my reports", "history", "show reports"):
        await _send_report_list(user_id, sender_to)
        return

    # ── 8. Moderation on user input ────────────────────────────────
    safe, mod = await moderation_check(body)
    if not safe:
        await _reply(sender_to,
            "I can't help with that. I'm here for blood-test questions only.",
            user_id, msg_type="refusal")
        await audit(user_id, "moderation_blocked", mod)
        return

    # ── 9. Run orchestrator ────────────────────────────────────────
    orch = await respond(user_id=user_id, user_message=body, user_hash=user_hash)
    text = orch.text or "Sorry, I had a hiccup. Could you repeat that?"

    # ── 10. Output guardrails ──────────────────────────────────────
    chk = validate_output(text, require_disclaimer=True)
    if chk.issues:
        log.info("guardrails.output_adjusted", issues=chk.issues)
    final_text = chk.text

    # ── 11. Send + persist ─────────────────────────────────────────
    await _reply(
        sender_to, final_text, user_id,
        msg_type="text",
        prompt_version=get_settings().prompt_version,
        model_used=orch.model,
        tokens_in=orch.tokens_in,
        tokens_out=orch.tokens_out,
        cost_usd=orch.cost_usd,
    )
    await increment_user_message_count(user_id)
    await add_user_spend(user_id, orch.cost_usd)

    # ── 12. Background: extract facts + maybe update summary ──────
    try:
        await extract_and_store_facts(
            user_id=user_id,
            user_msg=body,
            assistant_msg=final_text,
            source_conversation_id=inbound_conv_id,
            user_hash=user_hash,
        )
        await maybe_update_summary(user_id, user_hash=user_hash)
    except Exception as e:
        log.warning("handlers.post_processing_failed", error=str(e))


# ════════════════════════════════════════════════════════════════════════════
# PDF / IMAGE MESSAGE
# ════════════════════════════════════════════════════════════════════════════


async def handle_media(payload: dict[str, Any]) -> None:
    user_id = UUID(payload["user_id"])
    twilio_sid = payload.get("twilio_sid")
    sender_to = payload.get("sender")
    media_url = payload["media_url"]
    media_type = payload.get("media_type", "")
    caption = (payload.get("body") or "").strip()
    user_hash = await _user_hash_for(user_id)

    # ── 1. Onboarding gate ─────────────────────────────────────────
    user = await fetch_one("SELECT consent_given_at FROM users WHERE id = $1", user_id)
    if not user or not user.get("consent_given_at"):
        await _reply(sender_to, ONBOARDING_WELCOME, user_id, msg_type="onboarding")
        return

    # ── 2. Validate media ──────────────────────────────────────────
    v = validate_media(media_type)
    if not v.ok:
        await _reply(sender_to, v.refusal_text or "Unsupported file.", user_id, msg_type="refusal")
        return

    # ── 3. Rate limit + cost caps ─────────────────────────────────
    ok, msg = await enforce_pdf_rate_limit(user_id)
    if not ok:
        await _reply(sender_to, msg or "Quota hit.", user_id, msg_type="rate_limit")
        return
    ok, cmsg = await check_user_spend_cap(user_id)
    if not ok:
        await _reply(sender_to, cmsg or "Quota reached.", user_id, msg_type="quota")
        return

    # ── 4. Acknowledge fast ────────────────────────────────────────
    await send_whatsapp(sender_to, "Got your report — reading it now. This takes ~30–60 seconds.")

    # ── 5. Download from Twilio ────────────────────────────────────
    try:
        blob = await download_media(media_url)
    except Exception as e:
        log.error("handlers.download_failed", error=str(e))
        await _reply(sender_to, "I couldn't download that file. Try resending it?", user_id, msg_type="error")
        return
    if validate_media(media_type, byte_size=len(blob)).ok is False:
        await _reply(sender_to, "That file is too large.", user_id, msg_type="refusal")
        return

    # ── 6. Upload to Supabase Storage ──────────────────────────────
    try:
        storage_key = await upload_pdf(str(user_id), blob, source_msg_sid=twilio_sid)
    except Exception as e:
        log.error("handlers.upload_failed", error=str(e))
        await _reply(sender_to, "Storage hiccup on my side — please try again in a minute.",
                     user_id, msg_type="error")
        return

    # ── 7. Insert lab_reports row ──────────────────────────────────
    rec = await fetch_one(
        """
        INSERT INTO lab_reports (user_id, storage_path, source_msg_sid, status, byte_size)
        VALUES ($1, $2, $3, 'processing', $4)
        RETURNING id
        """,
        user_id, f"{get_settings().supabase_storage_bucket}/{storage_key}", twilio_sid, len(blob),
    )
    report_id = rec["id"]

    # ── 8. OCR ────────────────────────────────────────────────────
    if media_type.startswith("image/"):
        ocr_res = await extract_from_image(blob, user_hash=user_hash)
    else:
        ocr_res = await extract_from_pdf(blob, user_hash=user_hash)

    if not ocr_res.success:
        await execute(
            "UPDATE lab_reports SET status='failed', failure_reason=$2 WHERE id=$1",
            report_id, ocr_res.failure_reason or "ocr failed",
        )
        await _reply(sender_to,
            "I couldn't read that report clearly. Could you try a clearer photo or send the PDF directly?",
            user_id, msg_type="ocr_failed")
        return

    # ── 9. Block-list check (genetic / pathology / imaging reports) ──
    registry = get_registry()
    blocked, kw = registry.is_report_blocked(ocr_res.markdown[:3000])
    if blocked:
        await execute(
            "UPDATE lab_reports SET status='done', failure_reason=$2 WHERE id=$1",
            report_id, f"blocked_report:{kw}",
        )
        await _reply(sender_to, REFUSAL_BLOCKED_REPORT.format(kind=kw), user_id, msg_type="blocked_report")
        return

    # ── 10. Map results to biomarkers + tier them ──────────────────
    results = (ocr_res.structured.get("results") or [])
    measured_at = ocr_res.structured.get("report_date")
    rows = []
    tier1_results = []
    tier2_results = []
    unmapped = []
    for r in results:
        raw_name = (r.get("test_name") or "").strip()
        if not raw_name:
            continue
        match: Biomarker | None = registry.match(raw_name)
        loinc = match.loinc if match else None
        tier = match.tier if match else 2
        category = match.category if match else "unknown"
        norm_name = match.name if match else raw_name

        rows.append({
            "user_id": user_id,
            "report_id": report_id,
            "loinc_code": loinc,
            "test_name_raw": raw_name,
            "test_name_normalized": norm_name,
            "category": category,
            "tier": tier,
            "value": _safe_num(r.get("value")),
            "value_text": (r.get("value_text") or "").strip()[:80] or None,
            "unit": (r.get("unit") or "").strip()[:50] or None,
            "ref_range_text": (r.get("ref_range_text") or "").strip()[:200] or None,
            "ref_range_low": _safe_num(r.get("ref_range_low")),
            "ref_range_high": _safe_num(r.get("ref_range_high")),
            "status": _classify_status(r),
            "measured_at": _parse_date(measured_at),
        })
        snapshot = {"name": norm_name, "value": r.get("value"), "unit": r.get("unit"),
                    "ref": r.get("ref_range_text"), "flag": r.get("flag"), "tier": tier,
                    "specialist": match.specialist if match else None,
                    "category": category, "loinc": loinc,
                    "what_it_measures": match.what_it_measures if match else None}
        if not match:
            unmapped.append(snapshot)
        elif tier == 1:
            tier1_results.append(snapshot)
        else:
            tier2_results.append(snapshot)

    if rows:
        async with get_pool().acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO biomarker_results
                  (user_id, report_id, loinc_code, test_name_raw, test_name_normalized,
                   category, tier, value, value_text, unit, ref_range_text,
                   ref_range_low, ref_range_high, status, measured_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                """,
                [
                    (r["user_id"], r["report_id"], r["loinc_code"], r["test_name_raw"],
                     r["test_name_normalized"], r["category"], r["tier"], r["value"],
                     r["value_text"], r["unit"], r["ref_range_text"], r["ref_range_low"],
                     r["ref_range_high"], r["status"], r["measured_at"])
                    for r in rows
                ],
            )

    # ── 11. Generate interpretation ────────────────────────────────
    metadata_block = (
        f"Date: {measured_at or 'unknown'}\n"
        f"Type: {ocr_res.structured.get('report_type', 'blood_panel')}\n"
        f"Patient: {ocr_res.structured.get('patient_age', '?')} {ocr_res.structured.get('patient_sex', '?')}\n"
        f"Caption: {caption[:200] if caption else '(none)'}"
    )
    results_block = _format_results_for_llm(tier1_results, tier2_results, unmapped)
    user_ctx = await _user_context_compact(user_id)
    prompt = REPORT_INTERPRETATION_USER_TEMPLATE.format(
        metadata_block=metadata_block,
        results_block=results_block,
        user_context_block=user_ctx,
    )

    # Use orchestrator-style chat (same model + system prompt) but with
    # a more directive user message (the template above).
    from llm import chat as llm_chat
    from prompts import ORCHESTRATOR_SYSTEM
    res = await llm_chat(
        messages=[
            {"role": "system", "content": ORCHESTRATOR_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        model=get_settings().orchestrator_model,
        max_tokens=2000,
        temperature=0.4,
        user_hash=user_hash,
    )
    interpretation = res.text or "I read your report but had trouble explaining it. Please try again."

    # ── 12. Output guardrails ──────────────────────────────────────
    chk = validate_output(interpretation, require_disclaimer=True)
    final_text = chk.text

    # ── 13. Persist explanations per-biomarker ─────────────────────
    # We store the entire interpretation against each tier-1 biomarker mentioned
    # by name. This is cheap, and later memory.previous_explanation() can pull it.
    explanations: list[tuple] = []
    lt = final_text.lower()
    for snap in tier1_results:
        name = (snap.get("name") or "").lower()
        if name and name in lt:
            explanations.append((user_id, report_id, snap["loinc"], final_text))
    if explanations:
        async with get_pool().acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO report_biomarker_explanations
                  (user_id, report_id, loinc_code, explanation_text)
                VALUES ($1,$2,$3,$4)
                """,
                explanations,
            )

    # ── 14. Send reply + cleanup ───────────────────────────────────
    await execute(
        "UPDATE lab_reports SET status='done', processed_at=now(), ocr_provider=$2, ocr_raw_markdown=$3 WHERE id=$1",
        report_id, ocr_res.provider, ocr_res.markdown[:30000],
    )
    await _reply(sender_to, final_text, user_id,
                 msg_type="report_reply", model_used=res.model,
                 tokens_in=res.tokens_in, tokens_out=res.tokens_out,
                 cost_usd=res.cost_usd)
    await increment_user_pdf_count(user_id)
    await add_user_spend(user_id, res.cost_usd)
    await audit(user_id, "report_processed", {"report_id": str(report_id), "tiers": {
        "1": len(tier1_results), "2": len(tier2_results), "unmapped": len(unmapped),
    }})


# ════════════════════════════════════════════════════════════════════════════
# helpers
# ════════════════════════════════════════════════════════════════════════════


async def _user_hash_for(user_id: UUID) -> str:
    rec = await fetch_one("SELECT phone_hash FROM users WHERE id = $1", user_id)
    return (rec or {}).get("phone_hash", "")[:32]


async def _maybe_record_consent(user_id: UUID) -> None:
    await execute(
        """
        UPDATE users
           SET consent_given_at = COALESCE(consent_given_at, now()),
               consent_version  = COALESCE(consent_version, 'v1'),
               age_confirmed    = true
         WHERE id = $1
        """,
        user_id,
    )
    await audit(user_id, "consent_given", {"version": "v1"})


async def _delete_user_data(user_id: UUID) -> None:
    """DSAR — wipe everything except an audit-log record of the deletion."""
    # Soft-delete the user, hard-delete child rows
    await execute(
        """
        DELETE FROM biomarker_results       WHERE user_id = $1;
        """,
        user_id,
    )
    await execute("DELETE FROM report_biomarker_explanations WHERE user_id = $1", user_id)
    await execute("DELETE FROM conversations                 WHERE user_id = $1", user_id)
    await execute("DELETE FROM user_facts                    WHERE user_id = $1", user_id)
    await execute("DELETE FROM lab_reports                   WHERE user_id = $1", user_id)
    await execute("DELETE FROM rate_limit_events             WHERE user_id = $1", user_id)
    await execute(
        """
        UPDATE users
           SET phone_encrypted = NULL,
               conversation_summary = NULL,
               deleted_at = now()
         WHERE id = $1
        """,
        user_id,
    )
    await audit(user_id, "user_data_deleted", {"reason": "dsar"})


async def _send_report_list(user_id: UUID, sender_to: str | None) -> None:
    rows = await fetch_all(
        """
        SELECT id, uploaded_at, status,
               (SELECT count(*) FROM biomarker_results br WHERE br.report_id = lr.id) as n
          FROM lab_reports lr
         WHERE user_id = $1
         ORDER BY uploaded_at DESC
         LIMIT 20
        """,
        user_id,
    )
    if not rows:
        await _reply(sender_to, "You haven't uploaded any reports yet. Send a PDF to start.",
                     user_id, msg_type="text")
        return
    lines = ["Your reports:"]
    for i, r in enumerate(rows, 1):
        d = r["uploaded_at"].strftime("%d %b %Y")
        lines.append(f"{i}. {d} — {r['n']} markers ({r['status']})")
    await _reply(sender_to, "\n".join(lines), user_id, msg_type="text")


async def _user_context_compact(user_id: UUID) -> str:
    """Shorter version of memory.build_user_context_block for PDF interpretation prompt."""
    rec = await fetch_one("SELECT conversation_summary FROM users WHERE id = $1", user_id)
    summary = (rec or {}).get("conversation_summary") or ""
    facts = await fetch_all(
        "SELECT fact_type, fact_key, fact_value FROM user_facts "
        "WHERE user_id = $1 AND superseded_at IS NULL "
        "ORDER BY confidence DESC LIMIT 12",
        user_id,
    )
    parts = []
    if summary:
        parts.append(f"Long-term context: {summary}")
    if facts:
        parts.append("Known facts: " + "; ".join(
            f"{f['fact_type']}/{f['fact_key']}={f['fact_value']}" for f in facts
        ))
    return "\n".join(parts) or "(no prior context)"


def _format_results_for_llm(tier1: list[dict], tier2: list[dict], unmapped: list[dict]) -> str:
    parts: list[str] = []
    if tier1:
        parts.append("# Tier 1 — full interpretation expected")
        for r in tier1:
            parts.append(_one_line(r))
    if tier2:
        parts.append("\n# Tier 2 — specialist deferral required")
        for r in tier2:
            spec = r.get("specialist") or "specialist"
            parts.append(f"{_one_line(r)}  → defer to {spec}")
    if unmapped:
        parts.append("\n# Unrecognised tests — mention briefly, advise reviewing with doctor")
        for r in unmapped:
            parts.append(_one_line(r))
    return "\n".join(parts) if parts else "(no biomarkers extracted)"


def _one_line(r: dict) -> str:
    val = r.get("value")
    val_str = f"{val} {r.get('unit') or ''}".strip() if val is not None else "?"
    ref = r.get("ref") or ""
    flag = r.get("flag") or ""
    name = r.get("name") or "?"
    cat = r.get("category") or ""
    line = f"- {name} ({cat}): {val_str}"
    if ref:
        line += f"  (ref: {ref})"
    if flag:
        line += f"  [{flag}]"
    if r.get("what_it_measures"):
        line += f"\n   ↳ {r['what_it_measures']}"
    return line


def _safe_num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, str):
            v = v.replace(",", "").strip()
            if v.lower() in ("null", "none", "n/a", "-"):
                return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(d: Any) -> Any:
    if not d:
        return None
    if hasattr(d, "isoformat"):
        return d
    s = str(d).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        from datetime import date
        return date(int(m[1]), int(m[2]), int(m[3]))
    return None


def _classify_status(r: dict) -> str | None:
    """Crude initial status from flag column (LLM does deeper classification later)."""
    flag = (r.get("flag") or "").upper()
    if flag in ("HH", "LL"):
        return "critical"
    if flag == "H":
        return "high"
    if flag == "L":
        return "low"
    val = _safe_num(r.get("value"))
    lo = _safe_num(r.get("ref_range_low"))
    hi = _safe_num(r.get("ref_range_high"))
    if val is None:
        return None
    if hi is not None and val > hi:
        return "high"
    if lo is not None and val < lo:
        return "low"
    if lo is not None and hi is not None:
        return "normal"
    return None


async def _reply(
    sender: str | None,
    text: str,
    user_id: UUID,
    *,
    msg_type: str = "text",
    prompt_version: str | None = None,
    model_used: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> None:
    if not sender:
        log.warning("handlers.no_sender", user_id=str(user_id)[:8])
        return
    twilio_resp = await send_whatsapp(sender, text)
    sid = (twilio_resp or {}).get("sid")
    await append_conversation(
        user_id=user_id,
        role="assistant",
        content=text,
        msg_type=msg_type,
        twilio_sid=sid,
        prompt_version=prompt_version,
        model_used=model_used,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
