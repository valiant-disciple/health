"""Apply migrations to Supabase Postgres.

Usage:
    python scripts/setup_db.py             # apply all migrations in order
    python scripts/setup_db.py --check     # just print what would run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

import os

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="dry-run")
    parser.add_argument("--dsn", default=None, help="override DSN")
    args = parser.parse_args()

    # Prefer pooler URL (newer Supabase projects don't have direct DB hostname).
    dsn = (
        args.dsn
        or os.environ.get("SUPABASE_POOLER_URL")
        or os.environ.get("SUPABASE_DB_URL")
    )
    if not dsn:
        print("FATAL: set SUPABASE_POOLER_URL (or SUPABASE_DB_URL) or pass --dsn", file=sys.stderr)
        sys.exit(1)

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"No migrations in {MIGRATIONS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Migrations directory: {MIGRATIONS_DIR}")
    print(f"Connecting to: {dsn.split('@')[-1][:60] + '...'}")
    conn = await asyncpg.connect(dsn)
    try:
        for f in files:
            print(f"\n── {f.name} ──")
            sql = f.read_text()
            if args.check:
                print(f"  (dry-run, {len(sql)} chars)")
                continue
            try:
                await conn.execute(sql)
                print(f"  ✓ applied")
            except Exception as e:
                print(f"  ✗ FAILED: {e}", file=sys.stderr)
                sys.exit(1)
    finally:
        await conn.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(run())
