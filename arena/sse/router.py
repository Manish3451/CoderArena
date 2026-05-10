import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from arena.sse import broadcaster

router = APIRouter(tags=["sse"])


async def _event_gen(match_id: str) -> AsyncGenerator[str, None]:
    q = broadcaster.subscribe(match_id)
    try:
        yield json.dumps({"type": "connected", "match_id": match_id})
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=20)
                yield data
            except asyncio.TimeoutError:
                # Heartbeat to keep connection alive through proxies
                yield json.dumps({"type": "heartbeat"})
    finally:
        broadcaster.unsubscribe(match_id, q)


@router.get("/api/match/{match_id}/stream")
async def match_stream(match_id: str):
    """SSE stream for spectators. No auth required — matches are public to watch."""
    return EventSourceResponse(_event_gen(match_id))
