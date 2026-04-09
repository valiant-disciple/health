"""
Run once to create all Qdrant collections.
Usage: python infra/qdrant/setup_collections.py

Requires QDRANT_URL and QDRANT_API_KEY in environment or apps/ai-service/.env
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load from ai-service .env
load_dotenv(Path(__file__).parent.parent.parent / "apps/ai-service/.env")

from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, SparseVectorParams, PayloadSchemaType,
    SparseIndexParams,
)

QDRANT_URL     = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ["QDRANT_API_KEY"]

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def create_health_events():
    name = "health_events"
    existing = [c.name for c in client.get_collections().collections]
    if name in existing:
        print(f"  {name} already exists — skipping")
        return

    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": VectorParams(
                size=1024,               # BAAI/bge-large-en-v1.5 output dim
                distance=Distance.COSINE,
                on_disk=True,            # save RAM on free tier
            )
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=True)
            )
        },
    )

    # Payload indexes for pre-filtering (critical for per-user isolation)
    client.create_payload_index(name, "user_id",        PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "event_type",     PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "biomarker_code", PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "status",         PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "occurred_at",    PayloadSchemaType.DATETIME)

    print(f"  ✓ {name} created with dense+sparse vectors and 5 payload indexes")


def create_mem0_collection():
    """Mem0 creates its own collection automatically, but pre-create for control."""
    name = "mem0_health"
    existing = [c.name for c in client.get_collections().collections]
    if name in existing:
        print(f"  {name} already exists — skipping")
        return

    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": VectorParams(size=1536, distance=Distance.COSINE)
        },
    )
    client.create_payload_index(name, "user_id", PayloadSchemaType.KEYWORD)
    print(f"  ✓ {name} created")


def create_knowledge_collection():
    """Medical knowledge base (clinical guidelines, not per-user)."""
    name = "medical_kb"
    existing = [c.name for c in client.get_collections().collections]
    if name in existing:
        print(f"  {name} already exists — skipping")
        return

    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": VectorParams(size=1024, distance=Distance.COSINE, on_disk=True)
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=True))
        },
    )
    client.create_payload_index(name, "category",  PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "source",    PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "year",      PayloadSchemaType.INTEGER)
    print(f"  ✓ {name} created")


if __name__ == "__main__":
    print("Setting up Qdrant collections...")
    create_health_events()
    create_mem0_collection()
    create_knowledge_collection()
    print("\nAll collections ready.")
    print("\nExisting collections:")
    for c in client.get_collections().collections:
        print(f"  - {c.name}")
