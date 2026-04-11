"""6 core LangGraph tools for the health agent."""
from __future__ import annotations
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from services.context import assemble_patient_artifact
from services.memory import get_relevant_memories


@tool
async def get_user_health_context(
    focus: str = "general",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """
    Get a structured summary of the user's health context.
    Includes conditions, medications, recent lab results, trends, and known health facts.
    Always call this first before answering any health question.
    """
    artifact = await assemble_patient_artifact(user_id, focus)
    return artifact.to_prompt_str()


@tool
async def query_drug_interactions(
    drug_names: list[str],
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
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
    from services.vector import search_medical_kb
    results = await search_medical_kb(query=query, categories=categories, limit=5)
    if not results:
        return "No relevant guidelines found."
    return "\n\n".join(
        f"[{r.get('source','KB')}] {r.get('summary_text', r.get('content', ''))}"
        for r in results
    )


@tool
async def interpret_lab_result(
    loinc_code: str,
    value: float,
    unit: str,
    user_id: Annotated[str, InjectedState("user_id")] = "",
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
async def get_lab_trends(
    biomarker_code: str,
    months: int = 6,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
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
async def mem0_recall(
    query: str,
    scope: str | None = None,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """
    Recall specific long-term memories about the patient.
    scope options:
      'clinical'    — lab history, diagnoses, wearable trends
      'preference'  — dietary preferences, communication style, stated goals
      'behavioral'  — exercise habits, sleep patterns, lifestyle factors
      None          — search all memory types
    Use when you need to recall something specific the patient mentioned in a prior session,
    or when the pre-loaded memory context doesn't have enough detail.
    """
    from services.memory import mem0_recall as _recall
    results = await _recall(user_id, query, scope=scope)
    if not results:
        return "No relevant memories found."
    return "\n".join(
        f"• {r['memory']}" + (f" (score: {r['score']:.2f})" if r.get("score") else "")
        for r in results
    )


@tool
async def retrieve_graph_context(
    query: str,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """
    Query the bi-temporal health knowledge graph for facts about the patient.
    Returns extracted facts and episodes with temporal validity windows.
    Use this for questions about trends over time, historical changes, or
    relationship patterns — e.g. "has my HbA1c been rising?",
    "when did my resting HR start increasing?", "what happened after I started metformin?".
    """
    from services.memory import query_graph_context
    results = await query_graph_context(user_id, query, num_results=10)
    if not results:
        return "No relevant facts found in the health knowledge graph for this query."

    lines: list[str] = []
    for r in results:
        temporal = ""
        if r.get("valid_at"):
            temporal += f" [from {r['valid_at'][:10]}]"
        if r.get("invalid_at"):
            temporal += f" [until {r['invalid_at'][:10]}]"
        lines.append(f"• {r['content']}{temporal}")
    return "\n".join(lines)


@tool
async def flag_for_clinical_review(
    reason: str,
    urgency: str = "routine",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
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
        mem0_recall,
        retrieve_graph_context,
        query_drug_interactions,
        query_medical_kb,
        interpret_lab_result,
        get_lab_trends,
        flag_for_clinical_review,
    ]
