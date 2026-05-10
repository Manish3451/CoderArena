"""
In-process WebSocket connection manager.
Tracks players/spectators per match, broadcasts events, persists snapshots,
publishes to SSE for spectators, and fires hooks for the commentary pipeline.
"""
import asyncio
import json
import time
from collections import defaultdict
from typing import Callable

from fastapi import WebSocket

# {match_id: {ws: {user_id, player, role}}}
_connections: dict[str, dict[WebSocket, dict]] = defaultdict(dict)

# Last-seen snapshot per match per player, used to seed new connections
# {match_id: {player: (code, ts_ms)}}
_last_snapshot: dict[str, dict[str, tuple[str, int]]] = defaultdict(dict)

# Commentary pipeline hooks per match
# {match_id: [callable(match_id, player, code, prev_code, ts_ms)]}
_snapshot_hooks: dict[str, list[Callable]] = defaultdict(list)


def register_hook(match_id: str, hook: Callable):
    _snapshot_hooks[match_id].append(hook)


def unregister_hooks(match_id: str):
    _snapshot_hooks.pop(match_id, None)


async def connect(ws: WebSocket, match_id: str, user_id: str, player: str):
    await ws.accept()
    role = "player" if player in ("a", "b") else "spectator"
    _connections[match_id][ws] = {"user_id": user_id, "player": player, "role": role}

    # Replay current snapshot state to the new connection
    if match_id in _last_snapshot:
        for p, (code, ts) in _last_snapshot[match_id].items():
            try:
                await ws.send_text(json.dumps({
                    "type": "code_snapshot",
                    "player": p,
                    "code": code,
                    "ts_ms": ts,
                }))
            except Exception:
                pass


def disconnect(ws: WebSocket, match_id: str):
    _connections[match_id].pop(ws, None)
    if not _connections[match_id]:
        _connections.pop(match_id, None)


async def broadcast(match_id: str, message: dict, exclude: WebSocket | None = None):
    dead = []
    for ws, _meta in list(_connections.get(match_id, {}).items()):
        if ws is exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        disconnect(ws, match_id)


async def _persist_snapshot(match_id: str, player: str, code: str, ts_ms: int):
    """Save snapshot to DB. Best-effort, errors logged but never raised."""
    try:
        from arena.db import get_pool_async
        pool = await get_pool_async()
        async with pool.acquire() as conn:
            await conn.execute(
                "insert into match_snapshots (match_id, player, code, ts_ms) values ($1, $2, $3, $4)",
                match_id, player, code, ts_ms,
            )
    except Exception as e:
        print(f"[ws] snapshot persist failed for {match_id}/{player}: {e}")


async def _publish_to_sse(match_id: str, message: dict):
    try:
        from arena.sse import broadcaster as sse
        await sse.publish(match_id, message)
    except Exception as e:
        print(f"[ws] sse publish failed: {e}")


async def handle_code_update(
    ws: WebSocket, match_id: str, player: str, code: str
):
    """A player sent a code update. Broadcast, persist, hook agent."""
    ts_ms = int(time.time() * 1000)
    prev = _last_snapshot[match_id].get(player, ("", 0))
    prev_code = prev[0]
    _last_snapshot[match_id][player] = (code, ts_ms)

    msg = {"type": "code_snapshot", "player": player, "code": code, "ts_ms": ts_ms}

    # 1. Broadcast to other WS clients in this match
    await broadcast(match_id, msg, exclude=ws)

    # 2. Publish to SSE spectators
    asyncio.create_task(_publish_to_sse(match_id, msg))

    # 3. Persist to DB asynchronously (don't block the WS event loop)
    asyncio.create_task(_persist_snapshot(match_id, player, code, ts_ms))

    # 4. Fire commentary hooks
    for hook in _snapshot_hooks.get(match_id, []):
        asyncio.create_task(hook(match_id, player, code, prev_code, ts_ms))


async def broadcast_commentary(match_id: str, text: str, ts_ms: int):
    msg = {"type": "commentary", "text": text, "ts_ms": ts_ms}
    await broadcast(match_id, msg)
    await _publish_to_sse(match_id, msg)


async def broadcast_run_result(match_id: str, player: str, result: dict):
    msg = {"type": "run_result", "player": player, **result}
    await broadcast(match_id, msg)
    await _publish_to_sse(match_id, msg)


async def broadcast_match_event(match_id: str, event_type: str, payload: dict):
    msg = {"type": "match_event", "event": event_type, **payload}
    await broadcast(match_id, msg)
    await _publish_to_sse(match_id, msg)
