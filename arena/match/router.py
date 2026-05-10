from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from arena.db import SessionsDB, MatchesDB, ProblemsDB, use_db
from arena.auth.service import validate_session
from arena.match import service as match_svc

router = APIRouter(prefix="/api/match", tags=["match"])


class RunRequest(BaseModel):
    code: str


def get_session_sync(session: str):
    """Sync helper for getting session."""
    # We'll make _require_session async inside the router


# ── POST /api/match/create ────────────────────────────────────────────────────

@router.post("/create")
async def create_match(session: str = Cookie(None)):
    # Get user from session first
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")
    
    # Then create match
    async with use_db(ProblemsDB) as prob_conn:
        match = await match_svc.create_match(prob_conn, str(sess["user_id"]))

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
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")

    async with use_db(ProblemsDB) as prob_conn:
        try:
            match = await match_svc.join_match(prob_conn, join_code.upper(), str(sess["user_id"]))
        except ValueError as e:
            raise HTTPException(400, str(e))

    return {
        "match_id": str(match["id"]),
        "join_code": match["join_code"],
        "problem": {
            "slug": match["slug"] if "slug" in match else match["problem"]["slug"],
            "title": match["title"] if "title" in match else match["problem"]["title"],
            "difficulty": match["difficulty"] if "difficulty" in match else match["problem"]["difficulty"],
            "statement_md": match["statement_md"] if "statement_md" in match else match["problem"]["statement_md"],
            "test_cases": match["test_cases"] if "test_cases" in match else match["problem"]["test_cases"],
        },
    }


# ── GET /api/match/{match_id} ──────────────────────────────────────────────────

@router.get("/{match_id}")
async def get_match(match_id: str, session: str = Cookie(None)):
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")

    async with use_db(MatchesDB) as conn:
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            raise HTTPException(404, "Match not found")
        
        # Check access
        if match["player_a_id"] != sess["user_id"] and match["player_b_id"] != sess["user_id"]:
            raise HTTPException(403, "Not a player in this match")

    return {
        "id": str(match["id"]),
        "join_code": match["join_code"],
        "status": match["status"],
        "player_a": match["player_a_id"],
        "player_b": match["player_b_id"],
        "started_at": match["started_at"].isoformat() if match.get("started_at") else None,
        "problem": match.get("problem"),
    }


# ── POST /api/match/{match_id}/run ───────────────────────────────────────────────

@router.post("/{match_id}/run")
async def run_code(match_id: str, body: RunRequest, session: str = Cookie(None)):
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")

    async with use_db(MatchesDB) as conn:
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            raise HTTPException(404, "Match not found")
        
        player = "a" if match["player_a_id"] == str(sess["user_id"]) else "b"
        if player not in ("a", "b"):
            raise HTTPException(403, "Not a player in this match")

    result = await match_svc.run_code(match_id, player, body.code, match.get("problem", {}))
    return result


# ── POST /api/match/{match_id}/submit ───────────────────────────────────────────────

@router.post("/{match_id}/submit")
async def submitanswer(match_id: str, body: RunRequest, session: str = Cookie(None)):
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")

    async with use_db(MatchesDB) as conn:
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            raise HTTPException(404, "Match not found")
        
        player = "a" if match["player_a_id"] == str(sess["user_id"]) else "b"
        if player not in ("a", "b"):
            raise HTTPException(403, "Not a player in this match")

    result = await match_svc.submit_answer(match_id, player, body.code, match.get("problem", {}))
    return result


# ── GET /api/match/{match_id}/runs ─────────────────────────────────────────────

@router.get("/{match_id}/runs")
async def get_runs(match_id: str, session: str = Cookie(None)):
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")

    async with use_db(MatchesDB) as conn:
        match = await match_svc.get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            raise HTTPException(404, "Match not found")

    runs = await match_svc.get_runs(match_id)
    return {"runs": runs}


# ── GET /api/match/history ─────────────────────────────────────────────────

@router.get("/history")
async def match_history(session: str = Cookie(None)):
    async with use_db(SessionsDB) as sess_conn:
        sess = await validate_session(sess_conn, session)
        if not sess:
            raise HTTPException(401, "Not authenticated")

    async with use_db(MatchesDB) as conn:
        matches = await match_svc.get_user_matches(conn, str(sess["user_id"]))

    return {"matches": matches}