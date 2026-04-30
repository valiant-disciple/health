"""LLM tool definitions + handlers.

We expose a small set of tools the orchestrator can call to fetch user-specific
context. The dispatcher in `orchestrator.py` routes tool calls here.

Hard cap: 3 tool calls per turn, enforced in orchestrator.py.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from db import fetch_all, fetch_one
from memory import (
    all_previous_explanations,
    get_active_facts,
    previous_explanation,
    recent_lab_results,
)

log = structlog.get_logger()


# ── OpenAI tool schema definitions ────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_user_lab_history",
            "description": (
                "Fetch the user's past lab results, optionally filtered by biomarker. "
                "Returns chronological list (newest first). Use this when the user asks "
                "about trends, comparisons, or 'how has X changed'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "loinc_code": {
                        "type": "string",
                        "description": "Optional LOINC code to filter by (e.g. '13457-7' for LDL)",
                    },
                    "test_name": {
                        "type": "string",
                        "description": "Optional canonical biomarker name to filter by",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "How many days of history to return (default 365)",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_report_details",
            "description": "Fetch all biomarkers for a specific report by ID, or the most recent report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_id": {"type": "string", "description": "UUID of the report; omit for most recent"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_facts",
            "description": (
                "Fetch durable facts the user has previously shared "
                "(symptoms, conditions, medications, lifestyle). "
                "Use this when the user's question might connect to something they told us before."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": ["symptom", "condition", "medication", "lifestyle", "preference", "demographic", "any"],
                        "description": "Filter by fact type. 'any' returns all.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_prior_explanation",
            "description": (
                "Look up the explanation we previously gave for a specific biomarker. "
                "Use this when you want to recall what you told the user last time about a marker."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "loinc_code": {"type": "string", "description": "LOINC code, e.g. '13457-7'"},
                },
                "required": ["loinc_code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_user_reports",
            "description": "List all lab reports the user has uploaded (most recent first).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max reports to list (default 10)"},
                },
                "additionalProperties": False,
            },
        },
    },
]


# ── Tool dispatcher ───────────────────────────────────────────────────────


async def dispatch_tool_call(
    user_id: UUID,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Route a tool call to its handler. Always returns a JSON string."""
    try:
        if tool_name == "get_user_lab_history":
            return json.dumps(await _get_user_lab_history(user_id, arguments))
        if tool_name == "get_report_details":
            return json.dumps(await _get_report_details(user_id, arguments))
        if tool_name == "get_user_facts":
            return json.dumps(await _get_user_facts(user_id, arguments))
        if tool_name == "get_prior_explanation":
            return json.dumps(await _get_prior_explanation(user_id, arguments))
        if tool_name == "list_user_reports":
            return json.dumps(await _list_user_reports(user_id, arguments))
    except Exception as e:
        log.warning("tools.dispatch_error", tool=tool_name, error=str(e))
        return json.dumps({"error": str(e)})
    return json.dumps({"error": f"unknown tool: {tool_name}"})


async def _get_user_lab_history(user_id: UUID, args: dict) -> dict:
    days = int(args.get("days_back") or 365)
    loinc = args.get("loinc_code")
    name = args.get("test_name")

    if loinc:
        rows = await fetch_all(
            """
            SELECT loinc_code, test_name_normalized, value, unit, ref_range_text,
                   status, measured_at, tier
              FROM biomarker_results
             WHERE user_id = $1 AND loinc_code = $2
               AND (measured_at IS NULL OR measured_at >= current_date - make_interval(days => $3))
             ORDER BY measured_at DESC NULLS LAST, created_at DESC
             LIMIT 20
            """,
            user_id, loinc, days,
        )
    elif name:
        rows = await fetch_all(
            """
            SELECT loinc_code, test_name_normalized, value, unit, ref_range_text,
                   status, measured_at, tier
              FROM biomarker_results
             WHERE user_id = $1
               AND (LOWER(test_name_normalized) LIKE LOWER('%' || $2 || '%')
                    OR LOWER(test_name_raw) LIKE LOWER('%' || $2 || '%'))
               AND (measured_at IS NULL OR measured_at >= current_date - make_interval(days => $3))
             ORDER BY measured_at DESC NULLS LAST, created_at DESC
             LIMIT 20
            """,
            user_id, name, days,
        )
    else:
        rows = await recent_lab_results(user_id, days=days)
    return {"results": [_row_for_llm(r) for r in rows[:30]]}


async def _get_report_details(user_id: UUID, args: dict) -> dict:
    report_id = args.get("report_id")
    if not report_id:
        # Most recent
        rec = await fetch_one(
            "SELECT id, uploaded_at, status FROM lab_reports WHERE user_id = $1 "
            "ORDER BY uploaded_at DESC LIMIT 1",
            user_id,
        )
        if not rec:
            return {"error": "no reports yet"}
        report_id = rec["id"]

    rows = await fetch_all(
        """
        SELECT loinc_code, test_name_normalized, test_name_raw, value, unit,
               ref_range_text, status, tier, measured_at
          FROM biomarker_results
         WHERE user_id = $1 AND report_id = $2
         ORDER BY tier, category, test_name_normalized
        """,
        user_id, report_id,
    )
    report = await fetch_one(
        "SELECT id, uploaded_at, status FROM lab_reports WHERE id = $1 AND user_id = $2",
        report_id, user_id,
    )
    return {
        "report": dict(report) if report else None,
        "results": [_row_for_llm(r) for r in rows],
    }


async def _get_user_facts(user_id: UUID, args: dict) -> dict:
    facts = await get_active_facts(user_id, limit=40)
    ftype = args.get("fact_type")
    if ftype and ftype != "any":
        facts = [f for f in facts if f["fact_type"] == ftype]
    return {"facts": [
        {"type": f["fact_type"], "key": f["fact_key"], "value": f["fact_value"],
         "confidence": float(f["confidence"]), "learned_at": str(f["learned_at"])}
        for f in facts
    ]}


async def _get_prior_explanation(user_id: UUID, args: dict) -> dict:
    loinc = args.get("loinc_code")
    if not loinc:
        return {"error": "loinc_code required"}
    rec = await previous_explanation(user_id, loinc)
    if not rec:
        return {"explanation": None}
    return {
        "explanation": rec["explanation_text"],
        "given_at": str(rec["created_at"]),
    }


async def _list_user_reports(user_id: UUID, args: dict) -> dict:
    limit = int(args.get("limit") or 10)
    rows = await fetch_all(
        """
        SELECT id, uploaded_at, status, page_count,
               (SELECT count(*) FROM biomarker_results br WHERE br.report_id = lr.id) as biomarker_count
          FROM lab_reports lr
         WHERE user_id = $1
         ORDER BY uploaded_at DESC
         LIMIT $2
        """,
        user_id, limit,
    )
    return {"reports": [
        {"id": str(r["id"]), "uploaded_at": str(r["uploaded_at"]),
         "status": r["status"], "biomarkers": int(r["biomarker_count"] or 0)}
        for r in rows
    ]}


def _row_for_llm(r: dict) -> dict:
    return {
        "loinc": r.get("loinc_code"),
        "name": r.get("test_name_normalized") or r.get("test_name_raw"),
        "value": float(r["value"]) if r.get("value") is not None else None,
        "unit": r.get("unit"),
        "ref_range": r.get("ref_range_text"),
        "status": r.get("status"),
        "measured_at": str(r["measured_at"]) if r.get("measured_at") else None,
        "tier": r.get("tier"),
    }
