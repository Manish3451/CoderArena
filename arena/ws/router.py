import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from arena.db import DB
from arena.auth.service import validate_session
from arena.match.service import get_match
from arena.ws import manager

router = APIRouter(tags=["ws"])


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

    await websocket.send_text(json.dumps({
        "type": "connected",
        "player": player,
        "match_id": match_id,
        "status": match["status"],
    }))

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
