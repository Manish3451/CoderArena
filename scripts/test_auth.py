"""
End-to-end auth flow smoke test against the live Supabase DB.
Tests: guest creation, magic link request, token consumption, session validation.
Does NOT actually send email (uses dev mode if RESEND_API_KEY is unset).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from arena.db import get_pool_async, close_pool
from arena.auth import service


async def main():
    pool = await get_pool_async()

    async with pool.acquire() as conn:
        # 1. Create a guest user
        user = await service.create_guest_user(conn)
        print(f"[OK] Created guest: {user['handle']} (id={user['id']})")

        # 2. Create a session for them
        session_id = await service.create_session(conn, str(user["id"]))
        print(f"[OK] Created session: {session_id[:16]}...")

        # 3. Validate that session
        sess = await service.validate_session(conn, session_id)
        assert sess is not None, "Session validation failed!"
        assert sess["handle"] == user["handle"]
        print(f"[OK] Session validated: handle={sess['handle']}, is_guest={sess['is_guest']}")

        # 4. Magic link flow
        test_email = "test-flow@example.com"
        token = await service.create_magic_token(conn, test_email, "signup")
        print(f"[OK] Created magic token: {token[:16]}...")

        # 5. Consume token
        consumed = await service.consume_magic_token(conn, token)
        assert consumed is not None
        assert consumed["email"] == test_email
        print(f"[OK] Token consumed for: {consumed['email']}")

        # 6. Try to consume again (should fail)
        replay = await service.consume_magic_token(conn, token)
        assert replay is None, "Token replay should have failed!"
        print(f"[OK] Token replay correctly rejected")

        # 7. Cleanup
        await conn.execute("delete from sessions where id = $1", session_id)
        await conn.execute("delete from users where id = $1", user["id"])
        await conn.execute("delete from magic_link_tokens where token = $1", token)
        print(f"[OK] Cleanup done")

    await close_pool()
    print("\n[PASS] All auth flows working against live Supabase.")


if __name__ == "__main__":
    asyncio.run(main())
