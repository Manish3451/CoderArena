import secrets
import time
import httpx
from datetime import datetime, timezone, timedelta

from arena.config import settings

SESSION_TTL_DAYS = 30
TOKEN_TTL_MINUTES = 15
ADJECTIVES = [
    "Swift", "Bold", "Calm", "Keen", "Wise", "Bright", "Sharp", "Quick",
    "Brave", "Cool", "Dark", "Epic", "Fast", "Gold", "Iron", "Just",
]
NOUNS = [
    "Tiger", "Eagle", "Shark", "Wolf", "Bear", "Hawk", "Lion", "Puma",
    "Lynx", "Crane", "Viper", "Raven", "Cobra", "Drake", "Falcon", "Orca",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _random_handle() -> str:
    adj = secrets.choice(ADJECTIVES)
    noun = secrets.choice(NOUNS)
    num = secrets.randbelow(9000) + 1000
    return f"{adj}-{noun}-{num}"


def _new_token() -> str:
    return secrets.token_hex(32)


# ── Magic link ────────────────────────────────────────────────────────────────

async def create_magic_token(conn, email: str, intent: str) -> str:
    token = _new_token()
    expires_at = _now() + timedelta(minutes=TOKEN_TTL_MINUTES)
    await conn.execute(
        """
        insert into magic_link_tokens (token, email, intent, expires_at)
        values ($1, $2, $3, $4)
        """,
        token, email.lower().strip(), intent, expires_at,
    )
    return token


async def send_magic_email(email: str, token: str):
    if not settings.resend_api_key:
        # Dev mode: just print the link
        link = f"{settings.app_url}/auth/verify?token={token}"
        print(f"\n[DEV] Magic link for {email}:\n  {link}\n")
        return

    link = f"{settings.app_url}/auth/verify?token={token}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from,
                "to": [email],
                "subject": "Your CodeArena sign-in link",
                "html": f"""
                <p>Click the link below to sign in to CodeArena.</p>
                <p><a href="{link}">Sign in to CodeArena</a></p>
                <p>This link expires in 15 minutes.</p>
                <p>If you didn't request this, you can safely ignore it.</p>
                """,
            },
            timeout=10,
        )
        resp.raise_for_status()


async def consume_magic_token(conn, token: str) -> dict | None:
    """
    Validates token. Returns {'email', 'intent'} or None if invalid/expired/used.
    Marks token as used.
    """
    row = await conn.fetchrow(
        "select * from magic_link_tokens where token = $1",
        token,
    )
    if not row:
        return None
    if row["used_at"] is not None:
        return None
    if row["expires_at"] < _now():
        return None

    await conn.execute(
        "update magic_link_tokens set used_at = $1 where token = $2",
        _now(), token,
    )
    return {"email": row["email"], "intent": row["intent"]}


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_or_create_user_by_email(conn, email: str) -> dict:
    row = await conn.fetchrow("select * from users where email = $1", email)
    if row:
        # If the user was previously a guest who claimed their email,
        # update is_guest to false.
        if row["is_guest"]:
            await conn.execute(
                "update users set is_guest = false where id = $1", row["id"]
            )
        return dict(row)

    handle = _random_handle()
    # Ensure handle uniqueness (collision extremely unlikely but guard it)
    while await conn.fetchrow("select id from users where handle = $1", handle):
        handle = _random_handle()

    row = await conn.fetchrow(
        """
        insert into users (email, handle, is_guest)
        values ($1, $2, false)
        returning *
        """,
        email, handle,
    )
    return dict(row)


async def attach_email_to_guest(conn, user_id: str, email: str) -> dict:
    """Claim flow: guest user gets a permanent email attached."""
    row = await conn.fetchrow(
        """
        update users set email = $1, is_guest = false
        where id = $2
        returning *
        """,
        email, user_id,
    )
    return dict(row)


async def create_guest_user(conn) -> dict:
    handle = "Guest-" + _random_handle()
    while await conn.fetchrow("select id from users where handle = $1", handle):
        handle = "Guest-" + _random_handle()

    row = await conn.fetchrow(
        """
        insert into users (handle, is_guest)
        values ($1, true)
        returning *
        """,
        handle,
    )
    return dict(row)


async def get_user_by_id(conn, user_id: str) -> dict | None:
    row = await conn.fetchrow("select * from users where id = $1", user_id)
    return dict(row) if row else None


# ── Sessions ──────────────────────────────────────────────────────────────────

async def create_session(conn, user_id: str) -> str:
    session_id = _new_token()
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)
    await conn.execute(
        """
        insert into sessions (id, user_id, expires_at)
        values ($1, $2, $3)
        """,
        session_id, user_id, expires_at,
    )
    return session_id


async def validate_session(conn, session_id: str) -> dict | None:
    row = await conn.fetchrow(
        """
        select s.*, u.handle, u.email, u.is_guest
        from sessions s
        join users u on u.id = s.user_id
        where s.id = $1 and s.expires_at > now()
        """,
        session_id,
    )
    if not row:
        return None

    # Debounced last_seen_at update (skip if updated in last 60s)
    last_seen = row["last_seen_at"]
    if last_seen and (_now() - last_seen).total_seconds() > 60:
        await conn.execute(
            "update sessions set last_seen_at = $1 where id = $2",
            _now(), session_id,
        )

    return dict(row)


async def delete_session(conn, session_id: str):
    await conn.execute("delete from sessions where id = $1", session_id)
