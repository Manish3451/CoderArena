"""
Seed problems into the database.
Run with:  .\.venv\Scripts\python.exe scripts\seed.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arena.db import get_pool_async, close_pool
from arena.match.service import seed_problems


async def main():
    pool = await get_pool_async()
    async with pool.acquire() as conn:
        await seed_problems(conn)
        count = await conn.fetchval("select count(*) from problems")
        print(f"[OK] Problems in DB: {count}")
        rows = await conn.fetch("select slug, title, difficulty from problems order by difficulty, slug")
        for r in rows:
            print(f"     - [{r['difficulty']}] {r['slug']}: {r['title']}")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
