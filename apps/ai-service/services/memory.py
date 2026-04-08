"""
Memory layer:
  - Graphiti (Zep): bi-temporal health facts KG
  - Mem0: multi-scope conversation memory
"""
from __future__ import annotations
import structlog

from config import settings

log = structlog.get_logger()

_graphiti = None
_mem0 = None


async def init_graphiti():
    global _graphiti
    try:
        from graphiti_core import Graphiti
        _graphiti = Graphiti(settings.NEO4J_URI, settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        await _graphiti.build_indices_and_constraints()
        log.info("graphiti.initialized")
    except Exception as e:
        log.error("graphiti.init_failed", error=str(e))


async def close_graphiti():
    global _graphiti
    if _graphiti:
        await _graphiti.close()


def _get_mem0():
    global _mem0
    if _mem0 is None:
        try:
            from mem0 import Memory
            _mem0 = Memory.from_config({
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "url": settings.QDRANT_URL,
                        "api_key": settings.QDRANT_API_KEY,
                        "collection_name": "mem0_health",
                    },
                },
                "llm": {
                    "provider": "anthropic",
                    "config": {
                        "model": settings.FAST_MODEL,
                        "api_key": settings.ANTHROPIC_API_KEY,
                    },
                },
            })
        except Exception as e:
            log.error("mem0.init_failed", error=str(e))
    return _mem0


async def store_health_episode(user_id: str, event: dict):
    """Store a health event as a Graphiti bi-temporal episode."""
    if not _graphiti:
        return
    try:
        from graphiti_core.nodes import EpisodeType
        text = _format_event_as_episode(event)
        await _graphiti.add_episode(
            name=f"{user_id}:{event.get('event_type')}:{event.get('occurred_at')}",
            episode_body=text,
            source=EpisodeType.text,
            source_description=f"health event from {event.get('source','unknown')}",
            reference_time=event.get("occurred_at"),
            group_id=user_id,
        )
    except Exception as e:
        log.error("graphiti.store_episode_failed", error=str(e))


def _format_event_as_episode(event: dict) -> str:
    parts = [
        f"Event type: {event.get('event_type')}",
        f"Date: {event.get('occurred_at','unknown')}",
    ]
    if event.get("biomarker_name"):
        parts.append(
            f"{event['biomarker_name']} ({event.get('biomarker_code')}) = "
            f"{event.get('value_numeric')} {event.get('unit','')} — {event.get('status','')}"
        )
    if event.get("value_text"):
        parts.append(f"Notes: {event['value_text']}")
    return ". ".join(parts)


async def get_relevant_memories(user_id: str, query: str, limit: int = 5) -> str:
    """Get Mem0 memories relevant to query."""
    mem0 = _get_mem0()
    if not mem0:
        return ""
    try:
        result = mem0.search(query, user_id=user_id, limit=limit)
        memories = result.get("results", [])
        if not memories:
            return ""
        return "\n".join(f"- {m['memory']}" for m in memories)
    except Exception as e:
        log.error("mem0.search_failed", error=str(e))
        return ""


async def update_user_memory(user_id: str, messages: list):
    """Update Mem0 after conversation turn."""
    mem0 = _get_mem0()
    if not mem0:
        return
    try:
        mem0.add(messages, user_id=user_id)
    except Exception as e:
        log.error("mem0.update_failed", error=str(e))


async def extract_and_store_facts(user_id: str, interpretation: dict, report_id: str):
    """Extract facts from interpretation and store in Graphiti + Postgres."""
    if not _graphiti:
        return
    try:
        facts_text = _build_facts_episode(interpretation, report_id)
        from graphiti_core.nodes import EpisodeType
        from datetime import datetime, timezone
        await _graphiti.add_episode(
            name=f"{user_id}:interpretation:{report_id}",
            episode_body=facts_text,
            source=EpisodeType.text,
            source_description="lab report interpretation",
            reference_time=datetime.now(timezone.utc),
            group_id=user_id,
        )
        log.info("graphiti.facts_stored", user_id=user_id, report_id=report_id)
    except Exception as e:
        log.error("graphiti.extract_facts_failed", error=str(e))


def _build_facts_episode(interpretation: dict, report_id: str) -> str:
    lines = [f"Lab report {report_id} interpretation:"]
    for finding in interpretation.get("key_findings", []):
        lines.append(
            f"{finding.get('name')} ({finding.get('loinc')}) = {finding.get('value')} — "
            f"{finding.get('status')}. {finding.get('explanation','')}"
        )
    for suggestion in interpretation.get("dietary_suggestions", []):
        lines.append(f"Dietary suggestion: {suggestion.get('suggestion')} — {suggestion.get('mechanism')}")
    return "\n".join(lines)
