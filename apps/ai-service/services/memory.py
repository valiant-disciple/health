"""
Memory layer
  - Graphiti (graphiti-core 0.28+): bi-temporal health facts knowledge graph
  - Mem0 (mem0ai 1.0+): multi-scope conversation memory backed by Qdrant + Neo4j
"""
from __future__ import annotations
from datetime import datetime, timezone
import structlog

from config import settings

log = structlog.get_logger()

_graphiti = None
_mem0 = None


# ─── Graphiti ─────────────────────────────────────────────────────────────────

async def init_graphiti():
    global _graphiti
    try:
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.openai_client import OpenAIClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.embedder.openai import OpenAIEmbedder
        from graphiti_core.embedder.config import EmbedderConfig

        llm_client = OpenAIClient(
            config=LLMConfig(
                api_key=settings.OPENAI_API_KEY,
                model=settings.PRIMARY_MODEL,
            )
        )
        embedder = OpenAIEmbedder(
            config=EmbedderConfig(
                api_key=settings.OPENAI_API_KEY,
                embedding_model="text-embedding-3-small",
            )
        )
        _graphiti = Graphiti(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
            llm_client=llm_client,
            embedder=embedder,
        )
        await _graphiti.build_indices_and_constraints()
        log.info("graphiti.initialized")
    except Exception as e:
        log.error("graphiti.init_failed", error=str(e))


async def close_graphiti():
    global _graphiti
    if _graphiti:
        try:
            await _graphiti.close()
        except Exception:
            pass


# ─── Mem0 ─────────────────────────────────────────────────────────────────────

def _get_mem0():
    global _mem0
    if _mem0 is not None:
        return _mem0
    try:
        from mem0 import Memory
        _mem0 = Memory.from_config({
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url":             settings.QDRANT_URL,
                    "api_key":         settings.QDRANT_API_KEY,
                    "collection_name": "mem0_health",
                    "embedding_model_dims": 1536,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model":   settings.FAST_MODEL,
                    "api_key": settings.OPENAI_API_KEY,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model":   "text-embedding-3-small",
                    "api_key": settings.OPENAI_API_KEY,
                },
            },
            # Disable Neo4j graph store — Graphiti handles that
            "graph_store": {
                "provider": "neo4j",
                "config": {
                    "url":      settings.NEO4J_URI,
                    "username": settings.NEO4J_USER,
                    "password": settings.NEO4J_PASSWORD,
                },
            },
            "version": "v1.1",
        })
        log.info("mem0.initialized")
    except Exception as e:
        log.error("mem0.init_failed", error=str(e))
    return _mem0


# ─── Public API ───────────────────────────────────────────────────────────────

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
            source_description=f"health event from {event.get('source', 'unknown')}",
            reference_time=datetime.fromisoformat(event["occurred_at"])
                if event.get("occurred_at") else datetime.now(timezone.utc),
            group_id=user_id,
        )
    except Exception as e:
        log.error("graphiti.store_episode_failed", error=str(e))


async def extract_and_store_facts(user_id: str, interpretation: dict, report_id: str):
    """Extract facts from interpretation and store in Graphiti."""
    if not _graphiti:
        log.warning("graphiti.not_initialized — skipping fact extraction")
        return
    try:
        from graphiti_core.nodes import EpisodeType
        facts_text = _build_facts_episode(interpretation, report_id)
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


async def query_graph_context(
    user_id: str,
    query: str,
    num_results: int = 10,
) -> list[dict]:
    """
    Search the Graphiti bi-temporal KG for facts relevant to the query.
    Returns edges (extracted relationships/facts) and episodes (raw text passages)
    with their temporal validity windows — enabling questions like:
      "what was my HbA1c trajectory over 2024?"
      "when did my resting heart rate start trending up?"
    """
    if not _graphiti:
        return []
    try:
        from graphiti_core.search.search_config import SearchConfig
        results = await _graphiti.search_(
            query=query,
            group_ids=[user_id],
            config=SearchConfig(limit=num_results),
        )
        output: list[dict] = []
        for edge in results.edges:
            output.append({
                "type":       "fact",
                "content":    edge.fact,
                "valid_at":   edge.valid_at.isoformat() if edge.valid_at else None,
                "invalid_at": edge.invalid_at.isoformat() if edge.invalid_at else None,
            })
        for episode in results.episodes:
            output.append({
                "type":       "episode",
                "content":    episode.content,
                "valid_at":   episode.valid_at.isoformat() if episode.valid_at else None,
                "invalid_at": None,
            })
        return output
    except Exception as e:
        log.error("graphiti.search_failed", error=str(e))
        return []


async def get_relevant_memories(user_id: str, query: str, limit: int = 5) -> str:
    """Search Mem0 for memories relevant to the query (returns formatted string for system prompt)."""
    mem0 = _get_mem0()
    if not mem0:
        return ""
    try:
        results = mem0.search(query, user_id=user_id, limit=limit)
        # mem0ai 1.0 returns {"results": [...], "relations": [...]}
        memories = results.get("results", []) if isinstance(results, dict) else results
        if not memories:
            return ""
        return "\n".join(f"- {m.get('memory', m.get('text', ''))}" for m in memories)
    except Exception as e:
        log.error("mem0.search_failed", error=str(e))
        return ""


async def mem0_recall(
    user_id: str,
    query: str,
    scope: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Targeted Mem0 recall — returns structured list of matching memories.
    scope: 'clinical' | 'preference' | 'behavioral' | None (all scopes)
    The scope is prepended to the query so the embedding search favours
    memories tagged with that context.
    """
    mem0 = _get_mem0()
    if not mem0:
        return []
    try:
        search_query = f"[{scope}] {query}" if scope else query
        results = mem0.search(search_query, user_id=user_id, limit=limit)
        memories = results.get("results", []) if isinstance(results, dict) else results
        return [
            {
                "memory":   m.get("memory", m.get("text", "")),
                "score":    m.get("score"),
                "metadata": m.get("metadata", {}),
            }
            for m in (memories or [])
            if m.get("memory") or m.get("text")
        ]
    except Exception as e:
        log.error("mem0.recall_failed", error=str(e))
        return []


async def update_user_memory(user_id: str, messages: list, metadata: dict | None = None):
    """
    Add a conversation turn to Mem0.
    metadata: optional scope tags e.g. {"type": "preference"} or {"type": "behavioral"}
    """
    mem0 = _get_mem0()
    if not mem0:
        return
    try:
        mem0.add(messages, user_id=user_id, metadata=metadata)
    except Exception as e:
        log.error("mem0.update_failed", error=str(e))


async def store_clinical_memory(user_id: str, text: str) -> None:
    """
    Persist a clinical summary (lab results, diagnoses, wearable trends)
    in Mem0 as a long-term clinical memory.
    Tagged with metadata={"type": "clinical"} so the agent can filter to
    clinical scope via the mem0_recall tool.
    """
    mem0 = _get_mem0()
    if not mem0:
        return
    try:
        mem0.add(
            [{"role": "system", "content": text}],
            user_id=user_id,
            metadata={"type": "clinical"},
        )
        log.info("mem0.clinical_stored", user_id=user_id, length=len(text))
    except Exception as e:
        log.error("mem0.clinical_store_failed", error=str(e))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_event_as_episode(event: dict) -> str:
    parts = [
        f"Event type: {event.get('event_type')}",
        f"Date: {event.get('occurred_at', 'unknown')}",
    ]
    if event.get("biomarker_name"):
        parts.append(
            f"{event['biomarker_name']} ({event.get('biomarker_code')}) = "
            f"{event.get('value_numeric')} {event.get('unit', '')} — {event.get('status', '')}"
        )
    if event.get("value_text"):
        parts.append(f"Notes: {event['value_text']}")
    return ". ".join(parts)


def _build_facts_episode(interpretation: dict, report_id: str) -> str:
    lines = [f"Lab report {report_id} interpretation:"]
    for finding in interpretation.get("key_findings", []):
        lines.append(
            f"{finding.get('name')} ({finding.get('loinc')}) = {finding.get('value')} — "
            f"{finding.get('status')}. {finding.get('explanation', '')}"
        )
    for suggestion in interpretation.get("dietary_suggestions", []):
        lines.append(
            f"Dietary suggestion: {suggestion.get('suggestion')} — {suggestion.get('mechanism')}"
        )
    return "\n".join(lines)
