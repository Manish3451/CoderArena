import asyncpg
from arena.config import settings
import uuid

_pool: asyncpg.Pool | None = None
_in_memory = {
    "users": set(),
    "sessions": {},
    "magic_link_tokens": {},
    "problems": [],
    "matches": {},
    "match_runs": [],
    "match_snapshots": [],
    "match_events": [],
    "match_commentary": [],
}

def _get_id():
    return str(uuid.uuid4())

class InMemoryConn:
    def __init__(self, table: str):
        self.table = table

    async def execute(self, query: str, *args):
        q = query.lower()
        if self.table == "users":
            if "insert" in q and "returning" in q:
                new_user = {"id": _get_id(), "handle": args[0] if args else "guest", "is_guest": args[1] if len(args) > 1 else True, "email": args[2] if len(args) > 2 else None}
                _in_memory["users"].add(new_user)
                return new_user
            if "update" in q:
                for u in _in_memory["users"]:
                    if u.get("id") == args[1]:
                        u["handle"] = args[0]
                        if len(args) > 2:
                            u["email"] = args[2]
                        if len(args) > 3:
                            u["is_guest"] = args[3]
                        return u
        elif self.table == "sessions":
            if "insert" in q:
                _in_memory["sessions"][args[0]] = {"id": args[0], "user_id": args[1], "expires_at": args[2], "last_seen_at": args[2]}
                return {"id": args[0]}
            if "delete" in q:
                _in_memory["sessions"].pop(args[0], None)
        elif self.table == "magic_link_tokens":
            if "insert" in q:
                _in_memory["magic_link_tokens"][args[0]] = {"token": args[0], "email": args[1], "intent": args[2], "expires_at": args[3]}
                return {"token": args[0]}
            if "update" in q:
                t = _in_memory["magic_link_tokens"].get(args[1])
                if t:
                    t["used_at"] = args[0]
        elif self.table == "problems":
            if "insert" in q:
                _in_memory["problems"].append({"id": _get_id(), "slug": args[0], "title": args[1], "statement_md": args[2], "difficulty": args[3], "test_cases": args[4]})
                return _in_memory["problems"][-1]
        elif self.table == "matches":
            if "insert" in q and "returning" in q:
                new_match = {"id": _get_id(), "join_code": args[0], "problem_id": args[1], "player_a_id": args[2], "player_b_id": None, "status": "lobby"}
                _in_memory["matches"][new_match["id"]] = new_match
                return new_match
        return None

    async def fetchrow(self, query: str, *args):
        q = query.lower()
        if self.table == "users":
            if "where handle" in q:
                return {"id": _get_id(), "handle": args[0], "is_guest": True, "email": None}
            if "where id" in q:
                for u in _in_memory["users"]:
                    if u.get("id") == args[0]:
                        return u
                return None
        elif self.table == "sessions":
            if "where" in q:
                s = _in_memory["sessions"].get(args[0])
                if s:
                    # Fetch user to get handle
                    for u in _in_memory["users"]:
                        if u.get("id") == s.get("user_id"):
                            return {"id": s["id"], "user_id": s["user_id"], "handle": u.get("handle"), "is_guest": u.get("is_guest"), "email": u.get("email")}
                return s
        elif self.table == "magic_link_tokens":
            if "where token" in q:
                return _in_memory["magic_link_tokens"].get(args[0])
        elif self.table == "problems":
            if "random" in q:
                return {"id": _get_id(), "slug": "two-sum", "title": "Two Sum", "statement_md": "Test", "difficulty": "easy", "test_cases": "[]"}
        elif self.table == "matches":
            if "join_code" in q:
                for m in _in_memory["matches"].values():
                    if m.get("join_code") == args[0]:
                        return m
        return None

    async def fetch(self, query: str, *args):
        if self.table == "problems":
            return list(_in_memory["problems"])
        return []

    async def fetchval(self, query: str, *args):
        return None


def UsersDB(): return InMemoryConn("users")
def SessionsDB(): return InMemoryConn("sessions")
def MagicLinkDB(): return InMemoryConn("magic_link_tokens")
def ProblemsDB(): return InMemoryConn("problems")
def MatchesDB(): return InMemoryConn("matches")


def get_pool():
    if not settings.database_url:
        return None
    return _pool


async def get_pool_async():
    global _pool
    if _pool is None and settings.database_url:
        try:
            _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10, command_timeout=30)
        except Exception as e:
            print(f"DB connection failed: {e}")
            return None
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def use_db(db_factory):
    return InMemCtx(db_factory)


class InMemCtx:
    def __init__(self, factory):
        self._conn = factory()
    
    async def __aenter__(self):
        return self._conn
    
    async def __aexit__(self, *args):
        self._conn = None


class RealCtx:
    def __init__(self, pool):
        self._pool = pool
        self._conn = None
        
    async def __aenter__(self):
        self._conn = await self._pool.acquire()
        return self._conn
    
    async def __aexit__(self, *args):
        if self._conn and self._pool:
            await self._pool.release(self._conn)