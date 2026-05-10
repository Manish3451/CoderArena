from fastapi import APIRouter, Cookie, HTTPException, Response

from pydantic import BaseModel

from arena.config import settings
from arena.db import DB
from arena.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "session"

# Cross-origin cookie config:
# - In production (Vercel <-> Render are different domains): samesite="none", secure=True
# - In local dev (same origin or localhost): samesite="lax", secure=False
def _cookie_opts() -> dict:
    if settings.environment == "production":
        return dict(
            httponly=True,
            secure=True,         # required by browsers when SameSite=None
            samesite="none",     # required for cross-origin cookies
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
    return dict(
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


class EmailRequest(BaseModel):
    email: str


# ── POST /auth/request ────────────────────────────────────────────────────────

@router.post("/request")
async def request_magic_link(body: EmailRequest):
    """Send a magic link. Always returns 200 (don't leak whether email exists)."""
    email = body.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(422, "Invalid email")

    async with DB() as conn:
        existing = await conn.fetchrow("select id from users where email = $1", email)
        intent = "login" if existing else "signup"
        token = await service.create_magic_token(conn, email, intent)

    # If email send fails, surface a 500 so the user knows — silently swallowing
    # was the previous bug that hid the real problem.
    try:
        await service.send_magic_email(email, token)
    except Exception as e:
        raise HTTPException(500, f"Email send failed: {e}")

    return {"ok": True}


# ── GET /auth/verify ──────────────────────────────────────────────────────────

@router.get("/verify")
async def verify_magic_link(token: str):
    async with DB() as conn:
        data = await conn.fetchrow(
            "select * from magic_link_tokens where token = $1", token
        )
    if not data or data["used_at"] is not None:
        raise HTTPException(400, "Link already used or invalid")
    if data["expires_at"] < service._now():
        raise HTTPException(400, "Link expired")

    return {"valid": True, "email": data["email"], "intent": data["intent"]}


# ── POST /auth/complete ───────────────────────────────────────────────────────

@router.post("/complete")
async def complete_magic_link(token: str, response: Response):
    async with DB() as conn:
        consumed = await service.consume_magic_token(conn, token)
        if not consumed:
            raise HTTPException(400, "Link invalid, expired, or already used")
        user = await service.get_or_create_user_by_email(conn, consumed["email"])
        session_id = await service.create_session(conn, str(user["id"]))

    response.set_cookie(COOKIE_NAME, session_id, **_cookie_opts())
    return {"ok": True, "handle": user["handle"], "is_guest": user["is_guest"]}


# ── POST /auth/guest ──────────────────────────────────────────────────────────

@router.post("/guest")
async def create_guest(response: Response):
    async with DB() as conn:
        user = await service.create_guest_user(conn)
        session_id = await service.create_session(conn, str(user["id"]))

    response.set_cookie(COOKIE_NAME, session_id, **_cookie_opts())
    return {"ok": True, "handle": user["handle"], "is_guest": True}


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response, session: str = Cookie(None)):
    if session:
        async with DB() as conn:
            await service.delete_session(conn, session)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me")
async def me(session: str = Cookie(None)):
    if not session:
        raise HTTPException(401, "Not authenticated")
    async with DB() as conn:
        sess = await service.validate_session(conn, session)
    if not sess:
        raise HTTPException(401, "Session expired")
    return {
        "user_id": str(sess["user_id"]),
        "handle": sess["handle"],
        "email": sess["email"],
        "is_guest": sess["is_guest"],
    }


# ── GET /auth/token (for WS auth) ─────────────────────────────────────────────

@router.get("/token")
async def get_ws_token(session: str = Cookie(None)):
    if not session:
        raise HTTPException(401, "Not authenticated")
    async with DB() as conn:
        sess = await service.validate_session(conn, session)
    if not sess:
        raise HTTPException(401, "Session expired")
    return {"token": session}


# ── POST /auth/claim (guest -> permanent) ─────────────────────────────────────

@router.post("/claim")
async def claim_guest_account(body: EmailRequest, session: str = Cookie(None)):
    if not session:
        raise HTTPException(401, "Not authenticated")

    async with DB() as conn:
        sess = await service.validate_session(conn, session)
        if not sess or not sess["is_guest"]:
            raise HTTPException(400, "Must be logged in as a guest to claim")

        email = body.email.lower().strip()
        existing = await conn.fetchrow("select id from users where email = $1", email)
        if existing:
            raise HTTPException(400, "Email already in use")

        token = await service.create_magic_token(conn, email, "signup")

    try:
        await service.send_magic_email(email, token)
    except Exception as e:
        raise HTTPException(500, f"Email send failed: {e}")
    return {"ok": True}
