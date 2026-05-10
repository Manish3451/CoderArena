"""
In-process SSE broadcaster.
Spectators connect to GET /api/match/{id}/stream and receive all match events.
"""
import asyncio
import json
from collections import defaultdict

# {match_id: [asyncio.Queue]}
_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(match_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _queues[match_id].append(q)
    return q


def unsubscribe(match_id: str, q: asyncio.Queue):
    try:
        _queues[match_id].remove(q)
    except ValueError:
        pass
    if not _queues[match_id]:
        _queues.pop(match_id, None)


async def publish(match_id: str, event: dict):
    dead = []
    for q in list(_queues.get(match_id, [])):
        try:
            q.put_nowait(json.dumps(event))
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unsubscribe(match_id, q)


def subscriber_count(match_id: str) -> int:
    return len(_queues.get(match_id, []))
