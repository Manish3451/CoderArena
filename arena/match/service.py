import json
import random
import string
import time
import uuid
from datetime import datetime, timezone

from arena.db import ProblemsDB  # for seed_problems only
from arena.match.problems import PROBLEMS, WRAPPERS
from arena.match import piston as piston_api


def _now_ms() -> int:
    return int(time.time() * 1000)


def _join_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ── Problems ──────────────────────────────────────────────────────────────────

async def seed_problems(conn):
    """Insert seed problems if they don't exist yet."""
    for p in PROBLEMS:
        existing = await conn.fetchrow("select id from problems where slug = $1", p["slug"])
        if existing:
            continue
        await conn.execute(
            """
            insert into problems (slug, title, statement_md, difficulty,
                                  test_cases, hidden_test_cases, reference_solution)
            values ($1, $2, $3, $4, $5, $6, $7)
            """,
            p["slug"], p["title"], p["statement_md"], p["difficulty"],
            json.dumps(p["test_cases"]), json.dumps(p["hidden_test_cases"]),
            p.get("reference_solution"),
        )


async def get_random_problem(conn) -> dict:
    row = await conn.fetchrow("select * from problems order by random() limit 1")
    return dict(row)


async def get_problem(conn, problem_id: str) -> dict | None:
    row = await conn.fetchrow("select * from problems where id = $1", problem_id)
    return dict(row) if row else None


# ── Matches ───────────────────────────────────────────────────────────────────

async def create_match(conn, player_a_id: str) -> dict:
    problem = await get_random_problem(conn)

    join_code = _join_code()
    while await conn.fetchrow("select id from matches where join_code = $1", join_code):
        join_code = _join_code()

    row = await conn.fetchrow(
        """
        insert into matches (join_code, problem_id, player_a_id)
        values ($1, $2, $3)
        returning *
        """,
        join_code, problem["id"], player_a_id,
    )
    return {**dict(row), "problem": dict(problem)}


async def join_match(conn, join_code: str, player_b_id: str) -> dict:
    match = await conn.fetchrow(
        "select * from matches where join_code = $1", join_code
    )
    if not match:
        raise ValueError("Match not found")
    if match["status"] != "lobby":
        raise ValueError("Match already started or finished")
    if str(match["player_a_id"]) == player_b_id:
        raise ValueError("Cannot join your own match")

    row = await conn.fetchrow(
        """
        update matches
        set player_b_id = $1, status = 'live', started_at = now()
        where join_code = $2
        returning *
        """,
        player_b_id, join_code,
    )
    problem = await get_problem(conn, str(row["problem_id"]))
    return {**dict(row), "problem": problem}


async def get_match(conn, match_id: str, user_id: str) -> dict | None:
    row = await conn.fetchrow(
        """
        select m.*, p.slug, p.title, p.statement_md, p.difficulty,
               p.test_cases, p.hidden_test_cases
        from matches m
        join problems p on p.id = m.problem_id
        where m.id = $1
        """,
        match_id,
    )
    if not row:
        return None

    r = dict(row)
    r["player"] = (
        "a" if str(r["player_a_id"]) == user_id
        else "b" if str(r.get("player_b_id", "")) == user_id
        else "spectator"
    )
    r["test_cases"] = json.loads(r["test_cases"]) if isinstance(r["test_cases"], str) else r["test_cases"]
    # Never expose hidden test cases to the client
    r.pop("hidden_test_cases", None)
    return r


async def get_match_history(conn, user_id: str, limit: int = 10) -> list[dict]:
    rows = await conn.fetch(
        """
        select m.id, m.join_code, m.status, m.started_at, m.finished_at,
               m.winner_id, p.title, p.difficulty,
               ua.handle as player_a_handle, ub.handle as player_b_handle
        from matches m
        join problems p on p.id = m.problem_id
        join users ua on ua.id = m.player_a_id
        left join users ub on ub.id = m.player_b_id
        where m.player_a_id = $1 or m.player_b_id = $1
        order by m.created_at desc
        limit $2
        """,
        user_id, limit,
    )
    return [dict(r) for r in rows]


# ── Code execution ────────────────────────────────────────────────────────────

async def run_code(conn, match_id: str, player: str, user_code: str) -> dict:
    match = await conn.fetchrow(
        "select m.*, p.slug, p.test_cases from matches m join problems p on p.id = m.problem_id where m.id = $1",
        match_id,
    )
    if not match:
        raise ValueError("Match not found")

    slug = match["slug"]
    wrapper = WRAPPERS.get(slug)
    if not wrapper:
        raise ValueError(f"No wrapper for problem {slug}")

    raw_cases = match["test_cases"]
    test_cases = json.loads(raw_cases) if isinstance(raw_cases, str) else raw_cases

    result = await piston_api.run_tests(user_code, test_cases, wrapper)

    # Persist the run
    await conn.execute(
        """
        insert into match_runs
          (match_id, player, code, stdout, stderr, exit_code, runtime_ms,
           tests_passed, tests_total, ts_ms)
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        match_id, player, user_code,
        "\n".join(r["actual"] for r in result["results"]),
        "\n".join(r["stderr"] for r in result["results"] if r["stderr"]),
        0 if result["tests_passed"] == result["tests_total"] else 1,
        result["results"][0].get("runtime_ms", 0) if result["results"] else 0,
        result["tests_passed"], result["tests_total"],
        _now_ms(),
    )

    return result


async def submit_code(conn, match_id: str, player: str, user_code: str) -> dict:
    """Run against hidden test cases. If all pass, mark match finished."""
    match = await conn.fetchrow(
        "select m.*, p.slug, p.hidden_test_cases from matches m join problems p on p.id = m.problem_id where m.id = $1",
        match_id,
    )
    if not match:
        raise ValueError("Match not found")
    if match["status"] != "live":
        raise ValueError("Match is not live")

    slug = match["slug"]
    wrapper = WRAPPERS.get(slug)
    raw_hidden = match["hidden_test_cases"]
    hidden = json.loads(raw_hidden) if isinstance(raw_hidden, str) else raw_hidden

    result = await piston_api.run_tests(user_code, hidden, wrapper)
    all_passed = result["tests_passed"] == result["tests_total"]

    if all_passed:
        player_id_col = "player_a_id" if player == "a" else "player_b_id"
        winner_id = match[player_id_col]
        await conn.execute(
            """
            update matches set status = 'finished', finished_at = now(),
            winner_id = $1, result = $2
            where id = $3
            """,
            winner_id,
            json.dumps({"winner_player": player, "tests_passed": result["tests_passed"]}),
            match_id,
        )

    return {**result, "all_passed": all_passed}


# ── Snapshots ─────────────────────────────────────────────────────────────────

async def save_snapshot(conn, match_id: str, player: str, code: str) -> int:
    row = await conn.fetchrow(
        """
        insert into match_snapshots (match_id, player, code, ts_ms)
        values ($1, $2, $3, $4)
        returning id
        """,
        match_id, player, code, _now_ms(),
    )
    return row["id"]


async def get_snapshots(conn, match_id: str) -> list[dict]:
    rows = await conn.fetch(
        "select * from match_snapshots where match_id = $1 order by ts_ms",
        match_id,
    )
    return [dict(r) for r in rows]


# ── Commentary ────────────────────────────────────────────────────────────────

async def save_commentary(conn, match_id: str, text: str, model: str,
                          prompt_version: str, event_id: int | None = None) -> int:
    row = await conn.fetchrow(
        """
        insert into match_commentary (match_id, ts_ms, text, triggered_by_event_id, model, prompt_version)
        values ($1, $2, $3, $4, $5, $6)
        returning id
        """,
        match_id, _now_ms(), text, event_id, model, prompt_version,
    )
    return row["id"]


async def get_commentary(conn, match_id: str) -> list[dict]:
    rows = await conn.fetch(
        "select * from match_commentary where match_id = $1 order by ts_ms",
        match_id,
    )
    return [dict(r) for r in rows]
