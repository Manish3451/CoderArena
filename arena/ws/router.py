import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from arena.db import DB, get_pool_async
from arena.auth.service import validate_session
from arena.match.service import get_match
from arena.ws import manager

router = APIRouter(tags=["ws"])


def _start_pipeline_if_needed(match_id: str):
    """Lazily import and start the commentary pipeline. Failures are non-fatal."""
    try:
        from arena.agent.pipeline import start_pipeline
        start_pipeline(match_id, get_pool_async)
    except Exception as e:
        print(f"[ws] could not start commentary pipeline: {e}")


@router.websocket("/ws/match/{match_id}")
async def ws_match(
    websocket: WebSocket,
    match_id: str,
    token: str = Query(None),
):
    if not token:
        await websocket.close(code=4001, reason="No session token")
        return

    async with DB() as conn:
        sess = await validate_session(conn, token)
        if not sess:
            await websocket.close(code=4001, reason="Invalid session")
            return
        match = await get_match(conn, match_id, str(sess["user_id"]))
        if not match:
            await websocket.close(code=4004, reason="Match not found")
            return

    user_id = str(sess["user_id"])
    player = match["player"]

    await manager.connect(websocket, match_id, user_id, player)

    # Send connection confirmation to the joining client
    await websocket.send_text(json.dumps({
        "type": "connected",
        "player": player,
        "match_id": match_id,
        "status": match["status"],
    }))

    # Notify everyone else that this player/spectator just joined.
    # Player A in particular needs to know B has arrived so the UI exits "Waiting".
    await manager.broadcast_match_event(
        match_id,
        "player_joined",
        {"player": player, "status": match["status"]},
    )

    # Start the commentary pipeline once the match is live.
    if match["status"] == "live":
        _start_pipeline_if_needed(match_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "code_update" and player in ("a", "b"):
                code = msg.get("code", "")
                await manager.handle_code_update(websocket, match_id, player, code)

            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket, match_id)
        await manager.broadcast_match_event(
            match_id, "player_disconnected", {"player": player}
        )
