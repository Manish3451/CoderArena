# CodeArena — Architecture

A 10-minute read covering everything in the repo. If something here is wrong or
out of sync with the code, the code wins — fix this doc.

---

## 1. The big picture

```
+----------------------+        HTTPS         +------------------------+
| Next.js (Vercel)     |  <----- API ----->   | FastAPI (Render)       |
| - landing / auth UI  |                      | - auth, match, ws, sse |
| - lobby / play       |  <-- WebSocket -->   | - subprocess executor  |
| - watch / replay     |  <----- SSE -----    | - LangGraph agent      |
+----------------------+                      +------------------------+
                                                       |
                                                       | asyncpg
                                                       v
                                              +------------------+
                                              | Supabase Postgres|
                                              | (9 tables)       |
                                              +------------------+
                                                       ^
                                                       | direct conn
                                              +------------------+
                                              | scripts/         |
                                              | migrations/      |
                                              +------------------+

External services:
  - Resend (transactional email)
  - OpenAI API (gpt-4o-mini detector, gpt-4o writer)
```

Three deployments, one repo each, plus one shared database.

---

## 2. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 16 + Tailwind | Vercel-native, SSR, Monaco works |
| Editor | Monaco | Same engine as VS Code |
| Backend | FastAPI + asyncpg | Async-first, Render-friendly |
| DB | Supabase Postgres (pooler, port 6543) | Free tier, no maintenance |
| Real-time (players) | WebSockets in-process | No external broker needed at this scale |
| Real-time (spectators) | Server-Sent Events | One-way, simpler than WS |
| Auth | Magic link + guest, httpOnly cookie | No password storage today |
| Email | Resend | Best free DX |
| Code exec | Python `subprocess` on Render | Piston public API now blocks cloud IPs |
| Agent | LangGraph: gpt-4o-mini detector + gpt-4o writer | Detector is cheap, writer is good |
| Hosting | Vercel + Render free tiers | $0/month |

---

## 3. Repos

| Repo | What | Deployed to |
|---|---|---|
| `Manish3451/CoderArena` | Backend + repo root + frontend submodule pointer | Render |
| `Manish3451/CoderArean-Frontend` | Next.js app | Vercel |

The frontend lives as a git submodule under `frontend/` in the backend repo. When you change frontend code: commit + push the frontend repo first, then bump the submodule pointer in the backend repo.

---

## 4. Backend folder structure

```
arena/
  config.py             # pydantic-settings reads .env / Render env
  db.py                 # asyncpg pool + DB() context manager
  main.py               # FastAPI app, CORS, lifespan
  auth/
    service.py          # tokens, sessions, users, email send
    router.py           # /auth/request, verify, complete, guest, me, token, logout
  match/
    problems.py         # 5 seeded problems + per-problem stdin->func wrappers
    piston.py           # Code executor (subprocess; piston fallback if PISTON_API_KEY)
    service.py          # Match lifecycle, snapshots, commentary persistence
    router.py           # /api/match/* (history before /{id} due to path matching)
  ws/
    manager.py          # Connection registry, broadcast, snapshot persist, SSE bridge
    router.py           # /ws/match/{id} — auth via ?token, fires manager hooks
  sse/
    broadcaster.py      # Per-match queues for spectator subscribers
    router.py           # /api/match/{id}/stream
  agent/
    graph.py            # LangGraph: event_detector -> commentary_gen
    pipeline.py         # CommentaryPipeline: gates, persistence, broadcasts
    replay.py           # Offline replay over a recorded session
    eval.py             # F1 vs hand-labeled events, latency, cost
migrations/001_initial.sql
recordings/             # 3 hand-built session JSONs for offline eval
scripts/                # test_db, test_auth, test_executor, seed
evals/                  # phase0_report.md
```

---

## 5. Frontend folder structure

```
frontend/src/
  app/
    layout.tsx
    page.tsx                       # Landing
    auth/request/page.tsx          # Email input
    auth/verify/page.tsx           # Magic-link interstitial + complete
    lobby/page.tsx                 # Create / join / history
    play/[matchId]/page.tsx        # Players: 2 editors + run/submit + commentary
    watch/[matchId]/page.tsx       # Spectators: SSE-driven, read-only
    replay/[matchId]/page.tsx      # Scrubbable timeline
  components/GuestButton.tsx
  lib/
    api.ts        # Typed fetch client (strips trailing slash)
    ws.ts         # WS helper
    auth.ts       # sessionStorage helpers (handle, is_guest)
```

---

## 6. Data model (9 tables)

```
users               id, email?, handle, is_guest, created_at
magic_link_tokens   token, email, intent, expires_at, used_at
sessions            id, user_id, expires_at, last_seen_at

problems            id, slug, title, statement_md, difficulty,
                    test_cases (JSONB), hidden_test_cases (JSONB),
                    reference_solution
matches             id, join_code, problem_id, player_a_id, player_b_id,
                    status (lobby|live|finished), started_at, finished_at,
                    winner_id, result
match_runs          run history per submission
match_snapshots     code at each idle pause (used by replay + agent)
match_events        detected events from the agent
match_commentary    each commentary line with model + prompt_version
```

The schema is over-built for the MVP on purpose so we don't migrate every week.

---

## 7. Auth flow (current)

```
User clicks "Sign in with email"
  -> POST /auth/request {email}
     -> create magic_link_tokens row, expires_at = now + 15min
     -> Resend POST email with link to /auth/verify?token=XXX

User clicks link in email
  -> GET /auth/verify?token=XXX
     -> validate (exists, not used, not expired)
     -> show "Continue on this device?" interstitial

User clicks Continue
  -> POST /auth/complete?token=XXX
     -> mark token used
     -> get_or_create user by email
     -> create session row
     -> Set-Cookie: session=<id>; httpOnly; Secure; SameSite=None  (production)

Guest path: POST /auth/guest
  -> create user with is_guest=true and random handle
  -> same session cookie flow

Every authenticated request sends the session cookie. validate_session
also debounce-updates last_seen_at (1/min).
```

**Cookie config in production**: `SameSite=None`, `Secure=true` — required for cross-origin Vercel↔Render. In dev: `SameSite=Lax`, `Secure=false`.

---

## 8. Match flow (current)

```
Player A: lobby -> Create match
  -> POST /api/match/create
     -> pick a random problem
     -> generate 6-char join_code
     -> insert matches row, status=lobby
  -> redirect to /play/<match_id>
  -> open WS /ws/match/{id}?token=<session>

Player A's screen shows the join_code. They share it with B.

Player B: lobby -> Join
  -> POST /api/match/<code>/join
     -> assign player_b_id, status=live, started_at=now()
  -> redirect to /play/<match_id>
  -> open WS

Both WSs are now connected:
  - On B's connect, ws/router broadcasts player_joined
    -> A's UI exits "Waiting for opponent"
    -> commentary pipeline starts (registers a hook)

Coding loop:
  - Player types -> Monaco onChange (debounced 500ms)
  - WS send: {type: code_update, code}
  - ws/manager.handle_code_update:
      1. broadcast code_snapshot to other WS clients
      2. publish code_snapshot to SSE (spectators see it)
      3. async: insert into match_snapshots
      4. fire commentary hooks (the agent pipeline)

Run button:
  -> POST /api/match/<id>/run with current code
     -> run code through subprocess against visible test_cases
     -> insert into match_runs
     -> broadcast run_result (tests_passed/total) to everyone
  -> Result panel updates

Submit button:
  -> POST /api/match/<id>/submit
     -> run against hidden_test_cases
     -> if all pass: status=finished, winner_id=this player
     -> broadcast match_finished {winner, tests_passed, tests_total}
  -> Both screens show "You won" / "Opponent won"

Spectator: /watch/<id>
  -> open SSE /api/match/<id>/stream
  -> receives every code_snapshot, run_result, commentary, match_event
```

---

## 9. Commentary agent

```
arena/agent/graph.py
+--------------+      json mode       +--------------+
| event_detector |  -- gpt-4o-mini -> |              |
| (snapshot,     |                    | DetectedEvent|
|  prev_code)    |                    | (type, conf, |
|                |                    |  evidence)   |
+--------------+                      +--------------+
       |
       | confidence >= 0.6 and not "idle"
       v
+--------------+      streaming       +--------------+
| commentary_gen | --- gpt-4o ----->  | text         |
| (event +       |                    |              |
|  current code) |                    |              |
+--------------+                      +--------------+

arena/agent/pipeline.py — CommentaryPipeline
  - per-player 8s floor between comments (rate limit)
  - asyncio.create_task for fire-and-forget
  - on emit: WS broadcast + SSE publish + INSERT into match_commentary

Lifecycle:
  - WS router calls start_pipeline(match_id, get_pool_async) when match goes live
  - Hook registered in ws_manager._snapshot_hooks
  - Stays alive for the duration of the match (no cleanup yet — TODO)
```

Phase 0 eval results (offline, 3 hand-built sessions): F1 = 72%, ~1.3s detect latency, ~1.1s commentary latency, ~$0.05 per 10-min match.

---

## 10. Code execution

`arena/match/piston.py` runs Python in `asyncio.create_subprocess_exec` on the Render container itself. 5-second hard timeout per test case, all test cases run concurrently. If `PISTON_API_KEY` is set, it tries hosted Piston first and falls back to subprocess on 401/403.

For each problem there's a wrapper template in `problems.py` that takes the user's function and feeds it stdin → calls function → prints result. Test cases compare stdout strings.

**Caveat**: subprocess is not sandboxed. Trusted users only. Real fix is self-hosted Piston in Docker.

---

## 11. Deployment

| Service | Runtime | Build | Start |
|---|---|---|---|
| Render `codearena-api-caaf` | Python 3.11.9 (`runtime.txt`, `.python-version`, `PYTHON_VERSION` env) | `pip install -r requirements.txt` | `uvicorn arena.main:app --host 0.0.0.0 --port $PORT` |
| Vercel | Node 22 | `next build` | (Vercel-managed) |
| Supabase | Postgres 17 | n/a | n/a (managed) |

Required env on Render: `DATABASE_URL`, `OPENAI_API_KEY`, `RESEND_API_KEY`, `RESEND_FROM`, `APP_URL`, `ENVIRONMENT=production`, `PYTHON_VERSION=3.11.9`.
Required env on Vercel: `NEXT_PUBLIC_API_URL` (no trailing slash).

---

## 12. Known limitations / sharp edges

| Thing | Where | Risk |
|---|---|---|
| Subprocess executor isn't sandboxed | `arena/match/piston.py` | Friend could OOM the API container |
| Resend `onboarding@resend.dev` only delivers to account owner | `RESEND_FROM` | Strangers can't sign up |
| Render free tier sleeps after 15 min idle | Render | 30s cold start on first request |
| No 10-min match timer enforced server-side | `match/service.py` | Match can stay "live" forever if a player vanishes |
| No rate limiting on `/auth/request` | `auth/router.py` | Spam vector |
| Pipeline never cleaned up after match ends | `agent/pipeline.py` | Tiny memory leak per finished match |
| No test suite (only smoke scripts) | `scripts/` | Refactors are risky |
| Kimi key was invalid; using gpt-4o-mini | `agent/graph.py` | ~3x cost vs the original Kimi plan |

---

## 13. Where to look for things

| If you want to... | Open |
|---|---|
| Add a problem | `arena/match/problems.py` (and a wrapper) |
| Tune commentary | `arena/agent/graph.py` system prompts |
| Add an API route | `arena/<area>/router.py` |
| Change the play UI | `frontend/src/app/play/[matchId]/page.tsx` |
| Change auth UI | `frontend/src/app/auth/{request,verify}/page.tsx` |
| See deploy logs | Render dashboard > Logs tab |
| Reset DB | Supabase SQL editor + `migrations/001_initial.sql` |
| Run agent eval offline | `python -m arena.agent.eval` |
| Smoke-test against live Supabase | `python scripts/test_auth.py` |
