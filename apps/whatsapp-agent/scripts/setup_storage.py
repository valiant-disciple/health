"""Create the lab-reports bucket in Supabase Storage if it doesn't exist.

Usage:
    python scripts/setup_storage.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "lab-reports")
    if not url or not key:
        print("FATAL: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        sys.exit(1)

    headers = {"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        # List buckets
        r = await client.get(f"{url}/storage/v1/bucket", headers=headers)
        existing = [b["name"] for b in r.json()] if r.status_code < 300 else []
        print(f"Existing buckets: {existing}")
        if bucket in existing:
            print(f"✓ bucket {bucket!r} already exists")
            return
        # Create
        r = await client.post(
            f"{url}/storage/v1/bucket",
            headers=headers,
            json={"id": bucket, "name": bucket, "public": False, "file_size_limit": 15 * 1024 * 1024},
        )
        if r.status_code >= 300:
            print(f"FATAL: create failed: {r.status_code} {r.text}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ created bucket {bucket!r} (private)")


if __name__ == "__main__":
    asyncio.run(main())
