"""Qdrant hybrid search (dense + sparse, RRF fusion)."""
from __future__ import annotations
from datetime import datetime
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Prefetch, Query, FusionQuery, Fusion,
    Filter, FieldCondition, MatchValue, DatetimeRange,
)
from config import settings
import structlog

log = structlog.get_logger()

_qdrant: AsyncQdrantClient | None = None
_dense_model = None
_sparse_model = None


def get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    return _qdrant


def get_dense_model():
    global _dense_model
    if _dense_model is None:
        from fastembed import TextEmbedding
        _dense_model = TextEmbedding("BAAI/bge-large-en-v1.5")
    return _dense_model


def get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        from fastembed import SparseTextEmbedding
        _sparse_model = SparseTextEmbedding("Qdrant/bm25")
    return _sparse_model


async def hybrid_search(
    user_id: str,
    query: str,
    event_types: list[str] | None = None,
    since: datetime | None = None,
    limit: int = 10,
) -> list[dict]:
    qdrant = get_qdrant()
    dense  = get_dense_model()
    sparse = get_sparse_model()

    dense_vec  = list(dense.embed([query]))[0]
    sparse_vec = list(sparse.embed([query]))[0]

    must = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
    if event_types:
        must.append(FieldCondition(key="event_type", match=MatchValue(value=event_types[0])))
    if since:
        must.append(FieldCondition(key="occurred_at", range=DatetimeRange(gte=since.isoformat())))

    try:
        results = await qdrant.query_points(
            collection_name="health_events",
            prefetch=[
                Prefetch(query=dense_vec.tolist(), using="dense", limit=20),
                Prefetch(
                    query={"indices": sparse_vec.indices.tolist(), "values": sparse_vec.values.tolist()},
                    using="sparse",
                    limit=20,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=Filter(must=must),
            limit=limit,
            with_payload=True,
        )
        return [r.payload for r in results.points if r.payload]
    except Exception as e:
        log.error("vector.search_failed", error=str(e))
        return []


async def upsert_health_event(event_id: str, user_id: str, event: dict):
    """Embed a health event and upsert into Qdrant."""
    qdrant = get_qdrant()
    dense  = get_dense_model()
    sparse = get_sparse_model()

    summary = _build_summary(event)
    dense_vec  = list(dense.embed([summary]))[0]
    sparse_vec = list(sparse.embed([summary]))[0]

    from qdrant_client.models import PointStruct, SparseVector
    await qdrant.upsert(
        collection_name="health_events",
        points=[
            PointStruct(
                id=event_id,
                vector={
                    "dense":  dense_vec.tolist(),
                    "sparse": SparseVector(
                        indices=sparse_vec.indices.tolist(),
                        values=sparse_vec.values.tolist(),
                    ),
                },
                payload={
                    "user_id":        user_id,
                    "event_type":     event.get("event_type"),
                    "occurred_at":    event.get("occurred_at"),
                    "biomarker_code": event.get("biomarker_code"),
                    "biomarker_name": event.get("biomarker_name"),
                    "value_numeric":  event.get("value_numeric"),
                    "unit":           event.get("unit"),
                    "status":         event.get("status"),
                    "source":         event.get("source"),
                    "summary_text":   summary,
                    "metadata":       event.get("metadata", {}),
                },
            )
        ],
    )


async def search_medical_kb(
    query: str,
    categories: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Search the 'medical_kb' Qdrant collection (clinical guidelines, nutrient facts,
    drug monographs). This collection is indexed offline and is NOT user-scoped.
    """
    qdrant = get_qdrant()
    dense  = get_dense_model()
    sparse = get_sparse_model()

    dense_vec  = list(dense.embed([query]))[0]
    sparse_vec = list(sparse.embed([query]))[0]

    must = []
    if categories:
        from qdrant_client.models import FieldCondition, MatchAny
        must.append(FieldCondition(key="category", match=MatchAny(any=categories)))

    try:
        results = await qdrant.query_points(
            collection_name="medical_kb",
            prefetch=[
                Prefetch(query=dense_vec.tolist(), using="dense", limit=20),
                Prefetch(
                    query={"indices": sparse_vec.indices.tolist(), "values": sparse_vec.values.tolist()},
                    using="sparse",
                    limit=20,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=Filter(must=must) if must else None,
            limit=limit,
            with_payload=True,
        )
        return [r.payload for r in results.points if r.payload]
    except Exception as e:
        log.error("vector.kb_search_failed", error=str(e))
        return []


def _build_summary(event: dict) -> str:
    parts = []
    if event.get("biomarker_name"):
        parts.append(
            f"{event['biomarker_name']} {event.get('value_numeric','')} "
            f"{event.get('unit','')} ({event.get('status','')})"
        )
    if event.get("occurred_at"):
        parts.append(f"on {event['occurred_at'][:10]}")
    if event.get("source"):
        parts.append(f"from {event['source']}")
    return ". ".join(parts) if parts else str(event)
