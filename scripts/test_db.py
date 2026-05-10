"""
Smoke-test the Supabase connection and check migration state.
Run with:  .\.venv\Scripts\python.exe scripts\test_db.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arena.db import get_pool_async, close_pool


async def main():
    pool = await get_pool_async()
    async with pool.acquire() as conn:
        version = await conn.fetchval("select version()")
        print("[OK] Connected to Postgres")
        print(f"     Version: {version[:80]}")

        tables = await conn.fetch(
            "select tablename from pg_tables where schemaname = 'public' order by tablename"
        )
        names = [t["tablename"] for t in tables]
        print(f"\n[OK] Tables found ({len(names)}):")
        for n in names:
            print(f"     - {n}")

        required = {
            "users", "magic_link_tokens", "sessions",
            "problems", "matches", "match_runs",
            "match_snapshots", "match_events", "match_commentary",
        }
        missing = required - set(names)
        if missing:
            print(f"\n[!!] MISSING TABLES: {missing}")
            print("     Run migrations/001_initial.sql in the Supabase SQL editor.")
        else:
            print("\n[OK] All required tables present.")

            # Check if problems are seeded
            count = await conn.fetchval("select count(*) from problems")
            print(f"\n[OK] Problems seeded: {count}")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
