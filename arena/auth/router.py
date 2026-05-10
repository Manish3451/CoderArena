from fastapi import APIRouter, Cookie, HTTPException, Response, Request
from pydantic import BaseModel, EmailStr

from arena.db import UsersDB, MagicLinkDB, SessionsDB, use_db
from arena.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "session"
COOKIE_OPTS = dict(httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 24 * 30)


class EmailRequest(BaseModel):
    email: str


# ── POST /auth/request ────────────────────────────────────────────────────────

@router.post("/request")
async def request_magic_link(body: EmailRequest):
    email = body.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(422, "Invalid email")

    async with use_db(UsersDB) as conn:
        existing = await conn.fetchrow("select id from users where email = $1", email)
        intent = "login" if existing else "signup"
    
    async with use_db(MagicLinkDB) as token_conn:
        token = await service.create_magic_token(token_conn, email, intent)

    try:
        await service.send_magic_email(email, token)
    except Exception as e:
        pass  # Ignore email errors in production without API key

    return {"ok": True}


# ── POST /auth/signup (dev mode - instant guest) ────────────────────────────────
# ── POST /auth/guest (legacy alias) ───────────────────────────────────────────

@router.post("/signup")
@router.post("/guest")
async def signup(response: Response):
    async with use_db(UsersDB) as conn:
        user = await service.create_guest_user(conn)
    
    async with use_db(SessionsDB) as sess_conn:
        session_id = await service.create_session(sess_conn, str(user["id"]))

    response.set_cookie(COOKIE_NAME, session_id, **COOKIE_OPTS)
    return {"ok": True, "handle": user["handle"], "is_guest": True}


# ── GET /auth/verify ──────────────────────────────────────────────────────────

@router.get("/verify")
async def verify_magic_link(token: str):
    async with use_db(MagicLinkDB) as conn:
        data = await conn.fetchrow("select * from magic_link_tokens where token = $1", token)
    
    if not data or data.get("used_at") is not None:
        raise HTTPException(400, "Link already used or invalid")
    if data.get("expires_at") < service._now():
        raise HTTPException(400, "Link expired")

    return {"valid": True, "email": data.get("email"), "intent": data.get("intent")}


# ── POST /auth/complete ───────────────────────────────────────────────────────

@router.post("/complete")
async def complete_magic_link(token: str, response: Response):
    async with use_db(MagicLinkDB) as token_conn:
        consumed = await service.consume_magic_token(token_conn, token)
        if not consumed:
            raise HTTPException(400, "Link invalid, expired, or already used")

    async with use_db(UsersDB) as user_conn:
        user = await service.get_or_create_user_by_email(user_conn, consumed["email"])
    
    async with use_db(SessionsDB) as sess_conn:
        session_id = await service.create_session(sess_conn, str(user["id"]))

    response.set_cookie(COOKIE_NAME, session_id, **COOKIE_OPTS)
    return {"ok": True, "handle": user["handle"], "is_guest": user["is_guest"]}


# ── POST /auth/guest ──────────────────────────────────────────────────────────

@router.post("/guest")
async def create_guest(response: Response):
    async with use_db(UsersDB) as conn:
        user = await service.create_guest_user(conn)
    
    async with use_db(SessionsDB) as sess_conn:
        session_id = await service.create_session(sess_conn, str(user["id"]))

    response.set_cookie(COOKIE_NAME, session_id, **COOKIE_OPTS)
    return {"ok": True, "handle": user["handle"], "is_guest": True}


# ── POST /auth/claim ────────��─────────────────────────────────────────────────

@router.post("/claim")
async def claim_guest_account(body: EmailRequest, session: str = Cookie(None)):
    if not session:
        raise HTTPException(401, "Not authenticated")

    async with use_db(SessionsDB) as sess_conn:
        sess = await service.validate_session(sess_conn, session)
        if not sess or not sess.get("is_guest"):
            raise HTTPException(400, "Must be logged in as a guest to claim")

    email = body.email.lower().strip()
    async with use_db(UsersDB) as conn:
        existing = await conn.fetchrow("select id from users where email = $1", email)
        if existing:
            raise HTTPException(400, "Email already in use")

    async with use_db(MagicLinkDB) as token_conn:
        token = await service.create_magic_token(token_conn, email, "signup")

    await service.send_magic_email(email, token)
    return {"ok": True}


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response, session: str = Cookie(None)):
    if session:
        async with use_db(SessionsDB) as conn:
            await service.delete_session(conn, session)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me")
async def me(session: str = Cookie(None)):
    if not session:
        raise HTTPException(401, "Not authenticated")
    async with use_db(SessionsDB) as conn:
        sess = await service.validate_session(conn, session)
    if not sess:
        raise HTTPException(401, "Session expired")
    return {
        "user_id": str(sess.get("user_id")),
        "handle": sess.get("handle"),
        "email": sess.get("email"),
        "is_guest": sess.get("is_guest"),
    }


@router.get("/token")
async def get_ws_token(session: str = Cookie(None)):
    if not session:
        raise HTTPException(401, "Not authenticated")
    async with use_db(SessionsDB) as conn:
        sess = await service.validate_session(conn, session)
    if not sess:
        raise HTTPException(401, "Session expired")
    return {"token": session}