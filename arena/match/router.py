from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from arena.db import DB
from arena.auth.service import validate_session
from arena.match import service as match_svc

router = APIRouter(prefix="/api/match", tags=["match"])


class RunRequest(BaseModel):
    code: str


async def _require_session(session: str | None, conn):
    if not session:
        raise HTTPException(401, "Not authenticated")
    sess = await validate_session(conn, session)
    if not sess:
        raise HTTPException(401, "Session expired")
    return sess


# IMPORTANT: order matters — /history must be defined before /{match_id}
# otherwise FastAPI matches "history" as a match_id.

# ── GET /api/match/history ────────────────────────────────────────────────────

@router.get("/history")
async def match_history(session: str = Cookie(None)):
    async with DB() as conn:
        sess = await _require_session(session, conn)
        history = await match_svc.get_match_history(conn, str(sess["user_id"]))
    return {"matches": history}


# ── POST /api/match/create ────────────────────────────────────────────────────

@router.post("/create")
async def create_match(session: str = Cookie(None)):
    async with DB() as conn:
        sess = await _require_session(session, conn)
        match = await match_svc.create_match(conn, str(sess["user_id"]))

    return {
        "match_id": str(match["id"]),
        "join_code": match["join_code"],
        "problem": {
            "slug": match["problem"]["slug"],
            "title": match["problem"]["title"],
            "difficulty": match["problem"]["difficulty"],
            "statement_md": match["problem"]["statement_md"],
            "test_cases": match["problem"]["test_cases"],
        },
    }


# ── POST /api/match/{join_code}/join ──────────────────────────────────────────

@router.post("/{join_code}/join")
async def join_match(join_code: str, session: str = Cookie(None)):
    async with DB() as conn:
        sess = await _require_session(session, conn)
        try:
            match = await match_svc.join_match(conn, join_code.upper(), str(sess["user_id"]))
        except ValueError as e:
            raise HTTPException(400, str(e))

    return {
        "match_id": str(match["id"]),
        "join_code": match["join_code"],
        "problem": {
            "slug": match["problem"]["slug"],
            "title": match["problem"]["title"],
            "difficulty": match["problem"]["difficulty"],
            "statement_md": match["problem"]["statement_md"],
            "test_cases": match["problem"]["test_cases"],
        },
    }


# ── GET /api/match/{id} ───────────────────────────────────────────────────────

@router.get("/{match_id}")
async def get_match(match_id: str, session: str = Cookie(None)):
    async with DB() as conn:
        sess = await _require_session(session, conn)
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))

    if not match:
        raise HTTPException(404, "Match not found")
    return match


# ── POST /api/match/{id}/run ──────────────────────────────────────────────────

@router.post("/{match_id}/run")
async def run_code(match_id: str, body: RunRequest, session: str = Cookie(None)):
    async with DB() as conn:
        sess = await _require_session(session, conn)
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            raise HTTPException(404, "Match not found")
        if match["player"] not in ("a", "b"):
            raise HTTPException(403, "Spectators cannot run code")

        try:
            result = await match_svc.run_code(conn, match_id, match["player"], body.code)
        except ValueError as e:
            raise HTTPException(400, str(e))

    return result


# ── POST /api/match/{id}/submit ───────────────────────────────────────────────

@router.post("/{match_id}/submit")
async def submit_code(match_id: str, body: RunRequest, session: str = Cookie(None)):
    async with DB() as conn:
        sess = await _require_session(session, conn)
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            raise HTTPException(404, "Match not found")
        if match["player"] not in ("a", "b"):
            raise HTTPException(403, "Spectators cannot submit")

        try:
            result = await match_svc.submit_code(conn, match_id, match["player"], body.code)
        except ValueError as e:
            raise HTTPException(400, str(e))

    return result


# ── GET /api/match/{id}/replay ────────────────────────────────────────────────

@router.get("/{match_id}/replay")
async def get_replay(match_id: str):
    async with DB() as conn:
        snapshots = await match_svc.get_snapshots(conn, match_id)
        commentary = await match_svc.get_commentary(conn, match_id)
    return {"snapshots": snapshots, "commentary": commentary}


# ── GET /api/match/{id}/commentary ────────────────────────────────────────────

@router.get("/{match_id}/commentary")
async def get_commentary(match_id: str):
    async with DB() as conn:
        lines = await match_svc.get_commentary(conn, match_id)
    return {"commentary": lines}
