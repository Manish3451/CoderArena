"""
Single asyncpg pool, single context manager. No mocks, no fallbacks.
DATABASE_URL must be set or the app will fail loudly at startup.
"""
import asyncpg
from arena.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool_async() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Configure it in your environment (Render dashboard for prod, .env for local)."
            )
        # Supabase pooler-safe options:
        # - statement_cache_size=0 disables prepared-statement cache so it works
        #   under pgbouncer transaction mode without "prepared statement already
        #   exists" errors. Safe on session mode too.
        # - SSL is required by Supabase.
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
            statement_cache_size=0,
            ssl="require",
        )
    return _pool


# Backward-compat alias
get_pool = get_pool_async


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


class DB:
    """Usage: async with DB() as conn: row = await conn.fetchrow(...)"""

    def __init__(self):
        self._conn = None
        self._pool = None

    async def __aenter__(self):
        self._pool = await get_pool_async()
        self._conn = await self._pool.acquire()
        return self._conn

    async def __aexit__(self, *_):
        if self._conn and self._pool:
            await self._pool.release(self._conn)
        self._conn = None
        self._pool = None


# ── Compatibility shims so the modified routers keep working ─────────────────
# The routers were refactored to use `use_db(SessionsDB)` etc. — these all
# resolve to the same real Postgres connection, so the labels are decorative.

def _table_factory(_label: str):
    return None  # marker only


def UsersDB():       return "users"
def SessionsDB():    return "sessions"
def MagicLinkDB():   return "magic_link_tokens"
def ProblemsDB():    return "problems"
def MatchesDB():     return "matches"


def use_db(_factory=None):
    """All factories resolve to the same real Postgres connection."""
    return DB()
