"""
Patient artifact assembly.
Builds a structured, token-budgeted context object from multiple sources.
Never passes raw clinical text to the LLM — only structured provenance-tracked data.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import tiktoken
from supabase import AsyncClient

from config import settings
from services.db import get_supabase

ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class PatientArtifact:
    user_id: str
    demographics: dict
    active_conditions: list
    active_medications: list
    drug_interactions: list
    recent_labs: list
    key_trends: list
    health_facts: list
    dietary_restrictions: list
    focus: str = "general"
    token_count: int = 0

    def to_prompt_str(self) -> str:
        lines = [
            f"# Patient Context (user {self.user_id[:8]}...)",
            f"Focus: {self.focus}",
            "",
            "## Demographics",
        ]
        for k, v in self.demographics.items():
            if v:
                lines.append(f"- {k.replace('_', ' ').title()}: {v}")

        if self.active_conditions:
            lines.append("\n## Active Conditions")
            for c in self.active_conditions:
                lines.append(f"- {c['name']}" + (f" (since {c.get('diagnosed_at','')})" if c.get('diagnosed_at') else ""))

        if self.active_medications:
            lines.append("\n## Current Medications")
            for m in self.active_medications:
                lines.append(f"- {m['name']} {m.get('dose_amount','')} {m.get('dose_unit','')} {m.get('frequency','')}")

        if self.drug_interactions:
            lines.append("\n## Known Drug Interactions")
            for i in self.drug_interactions:
                lines.append(f"- {i['drug1']} ↔ {i['drug2']}: {i['severity']} — {i['mechanism']}")

        if self.dietary_restrictions:
            lines.append("\n## Dietary Restrictions")
            lines.append(", ".join(self.dietary_restrictions))

        if self.recent_labs:
            lines.append("\n## Recent Labs (last 90 days)")
            for lab in self.recent_labs:
                trend = f" [{lab.get('trend','')}]" if lab.get('trend') else ""
                lines.append(
                    f"- {lab['biomarker']} ({lab['loinc']}): {lab['latest_value']} "
                    f"as of {lab['latest_date'][:10]} — {lab['status'].upper()}{trend}"
                )

        if self.health_facts:
            lines.append("\n## Known Health Facts")
            for f in self.health_facts:
                lines.append(f"- {f['content']}")

        return "\n".join(lines)


async def assemble_patient_artifact(user_id: str, focus: str = "general") -> PatientArtifact:
    db: AsyncClient = await get_supabase()
    since_90d = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    # Fetch all sources in parallel
    profile_res, conditions_res, meds_res, labs_res, facts_res = await asyncio.gather(
        db.table("user_profile").select("*").eq("id", user_id).single().execute(),
        db.table("health_conditions").select("*").eq("user_id", user_id).is_("valid_until", None).limit(10).execute(),
        db.table("medications").select("*").eq("user_id", user_id).eq("status", "active").limit(15).execute(),
        db.table("health_events").select("*")
          .eq("user_id", user_id)
          .eq("event_type", "lab_result")
          .gte("occurred_at", since_90d)
          .order("occurred_at", desc=True)
          .limit(100)
          .execute(),
        db.table("health_facts").select("*").eq("user_id", user_id).is_("valid_until", None).limit(20).execute(),
    )

    profile    = profile_res.data or {}
    conditions = conditions_res.data or []
    meds       = meds_res.data or []
    labs       = labs_res.data or []
    facts      = facts_res.data or []

    demographics = {
        "age":              _age(profile.get("date_of_birth")),
        "sex":              profile.get("sex"),
        "height_cm":        profile.get("height_cm"),
        "weight_kg":        profile.get("weight_kg"),
        "activity_level":   profile.get("activity_level"),
        "health_goals":     ", ".join(profile.get("health_goals") or []),
    }

    compressed_labs = _compress_labs(labs)
    trends          = _extract_trends(labs)

    artifact = PatientArtifact(
        user_id=user_id,
        demographics=demographics,
        active_conditions=conditions,
        active_medications=meds,
        drug_interactions=[],          # populated by graph service when needed
        recent_labs=compressed_labs,
        key_trends=trends,
        health_facts=facts,
        dietary_restrictions=profile.get("dietary_restrictions") or [],
        focus=focus,
    )

    artifact.token_count = len(ENC.encode(artifact.to_prompt_str()))

    # If over budget, trim lower-priority sections
    if artifact.token_count > settings.MAX_CONTEXT_TOKENS:
        artifact = _trim_to_budget(artifact)

    return artifact


def _age(dob: str | None) -> str | None:
    if not dob:
        return None
    from dateutil.relativedelta import relativedelta
    delta = relativedelta(datetime.now(), datetime.fromisoformat(dob))
    return f"{delta.years} years"


def _compress_labs(labs: list) -> list:
    by_biomarker: dict[str, list] = {}
    for lab in labs:
        code = lab.get("biomarker_code") or "unknown"
        by_biomarker.setdefault(code, []).append(lab)

    compressed = []
    for code, readings in by_biomarker.items():
        readings.sort(key=lambda x: x["occurred_at"], reverse=True)
        latest = readings[0]
        compressed.append({
            "biomarker":    latest.get("biomarker_name", code),
            "loinc":        code,
            "latest_value": f"{latest.get('value_numeric','?')} {latest.get('unit','')}".strip(),
            "latest_date":  latest["occurred_at"],
            "status":       latest.get("status", "unknown"),
            "trend":        _compute_trend(readings),
            "readings_90d": len(readings),
        })
    return compressed


def _compute_trend(readings: list) -> str:
    if len(readings) < 2:
        return "first_reading"
    latest = readings[0].get("value_numeric") or 0
    prev   = readings[-1].get("value_numeric") or 0
    if prev == 0:
        return "stable"
    pct_change = (latest - prev) / abs(prev)
    if pct_change > 0.10:
        return "worsening" if readings[0].get("status") in ("high", "critical") else "increasing"
    if pct_change < -0.10:
        return "improving" if readings[0].get("status") in ("high", "critical") else "decreasing"
    return "stable"


def _extract_trends(labs: list) -> list:
    """Find biomarkers with significant change."""
    return []  # expanded in Day 6


def _trim_to_budget(artifact: PatientArtifact) -> PatientArtifact:
    """Drop facts first, then old labs, until under token budget."""
    while artifact.token_count > settings.MAX_CONTEXT_TOKENS and artifact.health_facts:
        artifact.health_facts.pop()
        artifact.token_count = len(ENC.encode(artifact.to_prompt_str()))
    while artifact.token_count > settings.MAX_CONTEXT_TOKENS and len(artifact.recent_labs) > 5:
        artifact.recent_labs.pop()
        artifact.token_count = len(ENC.encode(artifact.to_prompt_str()))
    return artifact
