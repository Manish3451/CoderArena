"""
Commentary pipeline: bridges WebSocket snapshot events to the LangGraph agent.

Registers a hook per match. When a player's code changes, the hook:
  1. Checks the should_comment? gate (8s floor, 30s ceiling, interestingness threshold)
  2. Runs the agent async
  3. Broadcasts commentary via the SSE broadcaster + WebSocket manager
  4. Persists to DB
"""
import asyncio
import time

from arena.agent.graph import Snapshot, run_on_snapshot
from arena.sse import broadcaster as sse
from arena.ws import manager as ws_manager

COMMENT_FLOOR_S = 8      # minimum seconds between comments per player
COMMENT_CEILING_S = 30   # force a comment if this many seconds have passed with activity
CONFIDENCE_THRESHOLD = 0.6
PROMPT_VERSION = "v1"


class CommentaryPipeline:
    def __init__(self, match_id: str, db_pool_getter):
        self.match_id = match_id
        self.get_pool = db_pool_getter  # async callable -> pool
        self._last_comment_ts: dict[str, float] = {}  # player -> epoch float
        self._pending_task: asyncio.Task | None = None

    async def on_snapshot(
        self, match_id: str, player: str, code: str, prev_code: str, ts_ms: int
    ):
        if not code.strip():
            return

        now = time.time()
        last = self._last_comment_ts.get(player, 0)
        elapsed = now - last

        if elapsed < COMMENT_FLOOR_S:
            return  # too soon

        # Run agent in a fire-and-forget task
        asyncio.create_task(
            self._run_agent(player, code, prev_code, ts_ms, now)
        )

    async def _run_agent(
        self, player: str, code: str, prev_code: str, ts_ms: int, start_time: float
    ):
        try:
            snapshot = Snapshot(
                player=player,
                code=code,
                prev_code=prev_code,
                ts_ms=ts_ms,
            )
            state = await asyncio.to_thread(run_on_snapshot, snapshot)

            if not state.should_comment or not state.commentary:
                return

            # Update last comment time
            self._last_comment_ts[player] = time.time()

            text = state.commentary

            # Broadcast to SSE stream (spectators)
            await sse.publish(self.match_id, {
                "type": "commentary",
                "text": text,
                "player": player,
                "ts_ms": ts_ms,
                "event_type": state.event.event_type if state.event else None,
            })

            # Broadcast to WS connections (players + spectators on /play)
            await ws_manager.broadcast_commentary(self.match_id, text, ts_ms)

            # Persist to DB
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                from arena.match.service import save_commentary
                await save_commentary(
                    conn, self.match_id, text,
                    model="gpt-4o",
                    prompt_version=PROMPT_VERSION,
                )

        except Exception as e:
            # Agent errors must never crash the WebSocket handler
            print(f"[commentary] Error for match {self.match_id}: {e}")


# Registry: one pipeline per active match
_pipelines: dict[str, CommentaryPipeline] = {}


def start_pipeline(match_id: str, db_pool_getter):
    if match_id not in _pipelines:
        pipeline = CommentaryPipeline(match_id, db_pool_getter)
        _pipelines[match_id] = pipeline
        ws_manager.register_hook(match_id, pipeline.on_snapshot)


def stop_pipeline(match_id: str):
    _pipelines.pop(match_id, None)
    ws_manager.unregister_hooks(match_id)
