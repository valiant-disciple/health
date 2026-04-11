"""
Run from repo root: python scripts/test_connections.py
Tests all external service connections before starting dev.
"""
import asyncio
import sys
import os
from pathlib import Path

# Load ai-service .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "apps/ai-service/.env")


def header(name: str):
    print(f"\n{'─'*50}")
    print(f"  Testing: {name}")
    print(f"{'─'*50}")


def ok(msg: str):  print(f"  ✓  {msg}")
def fail(msg: str): print(f"  ✗  {msg}")


# ── OpenAI ────────────────────────────────────────────────────────────────────
async def test_openai():
    header("OpenAI")
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say: ok"}],
        )
        ok(f"gpt-4o-mini reachable — response: {response.choices[0].message.content!r}")
        return True
    except Exception as e:
        fail(f"OpenAI failed: {e}")
        return False


# ── Supabase ──────────────────────────────────────────────────────────────────
async def test_supabase():
    header("Supabase")
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        fail("SUPABASE_SERVICE_ROLE_KEY not set — add it to apps/ai-service/.env")
        return False
    try:
        from supabase import acreate_client
        client = await acreate_client(url, key)
        # Try a simple query — will 200 even if table doesn't exist yet
        result = await client.table("user_profile").select("id").limit(1).execute()
        ok(f"Supabase connected — user_profile table exists ({len(result.data)} rows)")
        return True
    except Exception as e:
        fail(f"Supabase failed: {e}")
        return False


# ── Neo4j ─────────────────────────────────────────────────────────────────────
async def test_neo4j():
    header("Neo4j AuraDB")
    try:
        from neo4j import AsyncGraphDatabase
        uri  = os.environ["NEO4J_URI"]
        user = os.environ.get("NEO4J_USER", "neo4j")
        pwd  = os.environ["NEO4J_PASSWORD"]
        db   = os.environ.get("NEO4J_DATABASE", "neo4j")

        driver = AsyncGraphDatabase.driver(uri, auth=(user, pwd))
        async with driver.session(database=db) as session:
            result = await session.run("RETURN 'connected' AS status")
            record = await result.single()
            ok(f"Neo4j AuraDB connected — db={db}, status={record['status']}")
        await driver.close()
        return True
    except Exception as e:
        fail(f"Neo4j failed: {e}")
        return False


# ── Qdrant ────────────────────────────────────────────────────────────────────
async def test_qdrant():
    header("Qdrant Cloud")
    try:
        from qdrant_client import AsyncQdrantClient
        client = AsyncQdrantClient(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ["QDRANT_API_KEY"],
        )
        collections = await client.get_collections()
        names = [c.name for c in collections.collections]
        if names:
            ok(f"Qdrant connected — collections: {', '.join(names)}")
        else:
            ok("Qdrant connected — no collections yet (run infra/qdrant/setup_collections.py)")
        await client.close()
        return True
    except Exception as e:
        fail(f"Qdrant failed: {e}")
        return False


# ── Langfuse ──────────────────────────────────────────────────────────────────
def test_langfuse():
    header("Langfuse")
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
            host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        ok("Langfuse client initialized (auth check on first trace)")
        return True
    except Exception as e:
        fail(f"Langfuse failed: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("\n" + "="*50)
    print("  health — Connection Tests")
    print("="*50)

    results = await asyncio.gather(
        test_openai(),
        test_supabase(),
        test_neo4j(),
        test_qdrant(),
        return_exceptions=True,
    )

    lf_ok = test_langfuse()

    passed = sum(1 for r in results if r is True) + (1 if lf_ok else 0)
    total  = len(results) + 1

    print(f"\n{'='*50}")
    print(f"  Results: {passed}/{total} passed")
    print(f"{'='*50}\n")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
