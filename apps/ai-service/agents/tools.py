"""6 core LangGraph tools for the health agent."""
from __future__ import annotations
from langchain_core.tools import tool

from services.context import assemble_patient_artifact
from services.memory import get_relevant_memories


@tool
async def get_user_health_context(user_id: str, focus: str = "general") -> str:
    """
    Get a structured summary of the user's health context.
    Includes conditions, medications, recent lab results, trends, and known health facts.
    Always call this first before answering any health question.
    """
    artifact = await assemble_patient_artifact(user_id, focus)
    return artifact.to_prompt_str()


@tool
async def query_drug_interactions(user_id: str, drug_names: list[str]) -> str:
    """
    Check Neo4j for drug-drug and drug-nutrient interactions.
    Pass a list of drug names (generic or brand).
    Returns interactions with severity (major/moderate/minor) and mechanism.
    """
    from services.graph import get_drug_interactions
    interactions = await get_drug_interactions(user_id, drug_names)
    if not interactions:
        return "No significant interactions found between these medications."
    return "\n".join(
        f"• {i['drug1']} ↔ {i['drug2']}: {i['severity'].upper()} — {i['mechanism']}"
        for i in interactions
    )


@tool
async def query_medical_kb(query: str, categories: list[str] | None = None) -> str:
    """
    Search clinical guidelines and medical knowledge base using hybrid search.
    Use for evidence-based information about conditions, nutrients, or biomarkers.
    """
    from services.vector import hybrid_search
    results = await hybrid_search(
        user_id="__knowledge__",
        query=query,
        event_types=categories,
        limit=5,
    )
    if not results:
        return "No relevant guidelines found."
    return "\n\n".join(
        f"[{r.get('source','KB')}] {r.get('summary_text', r.get('value_text', ''))}"
        for r in results
    )


@tool
async def interpret_lab_result(
    user_id: str,
    loinc_code: str,
    value: float,
    unit: str,
) -> str:
    """
    Contextualize a specific lab value against the user's own history.
    Returns trend, comparison to prior values, and relevant conditions/drugs.
    """
    from services.db import get_supabase
    db = await get_supabase()
    history = await db.table("health_events") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("biomarker_code", loinc_code) \
        .order("occurred_at", desc=True) \
        .limit(10) \
        .execute()
    readings = history.data or []
    if not readings:
        return f"No prior readings found for LOINC {loinc_code}. Current value: {value} {unit}."

    values = [r["value_numeric"] for r in readings if r.get("value_numeric")]
    avg = sum(values) / len(values) if values else value
    latest_date = readings[0]["occurred_at"][:10]
    return (
        f"LOINC {loinc_code}: Current {value} {unit}. "
        f"Prior {len(values)} readings avg: {avg:.1f} {unit}. "
        f"Last reading: {readings[0].get('value_numeric')} {unit} on {latest_date} "
        f"(status: {readings[0].get('status','unknown')})."
    )


@tool
async def get_lab_trends(user_id: str, biomarker_code: str, months: int = 6) -> str:
    """
    Get temporal trend for a specific biomarker over the past N months.
    Returns list of readings with dates, values, and trend direction.
    """
    from services.db import get_supabase
    from datetime import datetime, timedelta, timezone
    db = await get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=months * 30)).isoformat()
    result = await db.table("health_events") \
        .select("occurred_at,value_numeric,unit,status") \
        .eq("user_id", user_id) \
        .eq("biomarker_code", biomarker_code) \
        .gte("occurred_at", since) \
        .order("occurred_at") \
        .execute()
    readings = result.data or []
    if not readings:
        return f"No readings found for {biomarker_code} in past {months} months."

    lines = [f"Trend for {biomarker_code} ({months} months, {len(readings)} readings):"]
    for r in readings:
        lines.append(f"  {r['occurred_at'][:10]}: {r.get('value_numeric')} {r.get('unit','')} [{r.get('status','')}]")
    return "\n".join(lines)


@tool
async def flag_for_clinical_review(user_id: str, reason: str, urgency: str = "routine") -> str:
    """
    Flag a finding for clinical review. Use when:
    - Lab value is critical
    - Drug interaction is major severity
    - Symptom pattern suggests urgent evaluation
    urgency: 'routine' | 'soon' | 'urgent'
    """
    from services.db import get_supabase
    from datetime import datetime, timezone
    db = await get_supabase()
    await db.table("health_facts").insert({
        "user_id": user_id,
        "fact_type": "clinical_flag",
        "content": f"[{urgency.upper()}] {reason}",
        "confidence": 1.0,
        "valid_from": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return f"Flagged for clinical review ({urgency}): {reason}"


def get_tools():
    return [
        get_user_health_context,
        query_drug_interactions,
        query_medical_kb,
        interpret_lab_result,
        get_lab_trends,
        flag_for_clinical_review,
    ]
