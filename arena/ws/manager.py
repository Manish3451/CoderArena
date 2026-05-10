"""
In-process WebSocket connection manager.
Tracks connected players/spectators per match and broadcasts events.
"""
import asyncio
import json
import time
from collections import defaultdict
from typing import Callable

from fastapi import WebSocket

# {match_id: {ws: {user_id, player, role}}}
_connections: dict[str, dict[WebSocket, dict]] = defaultdict(dict)

# Snapshot buffers for the commentary agent
# {match_id: {player: (code, ts_ms)}}
_last_snapshot: dict[str, dict[str, tuple[str, int]]] = defaultdict(dict)

# Callbacks registered by the commentary pipeline
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

    # Send current snapshot state to newly connected client
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
    for ws, meta in list(_connections.get(match_id, {}).items()):
        if ws is exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        disconnect(ws, match_id)


async def handle_code_update(
    ws: WebSocket, match_id: str, player: str, code: str
):
    """Called when a player sends a code update. Broadcasts + fires snapshot hooks."""
    ts_ms = int(time.time() * 1000)
    prev = _last_snapshot[match_id].get(player, ("", 0))
    prev_code = prev[0]

    _last_snapshot[match_id][player] = (code, ts_ms)

    msg = {"type": "code_snapshot", "player": player, "code": code, "ts_ms": ts_ms}
    await broadcast(match_id, msg, exclude=ws)

    # Fire snapshot hooks (commentary agent) asynchronously
    for hook in _snapshot_hooks.get(match_id, []):
        asyncio.create_task(hook(match_id, player, code, prev_code, ts_ms))


async def broadcast_commentary(match_id: str, text: str, ts_ms: int):
    await broadcast(match_id, {"type": "commentary", "text": text, "ts_ms": ts_ms})


async def broadcast_run_result(match_id: str, player: str, result: dict):
    await broadcast(match_id, {"type": "run_result", "player": player, **result})


async def broadcast_match_event(match_id: str, event_type: str, payload: dict):
    await broadcast(match_id, {"type": "match_event", "event": event_type, **payload})
