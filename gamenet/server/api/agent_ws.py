"""Agent WebSocket gateway: live server -> agent push (Master Spec 326).

URL: /api/v1/agent/ws?token=<agent-token> (query auth: WS clients cannot
set Authorization headers reliably).

Client -> server messages:
  {"type": "HEARTBEAT", "payload": {...}}  (same payload as REST heartbeat)
  {"type": "ACK", "command_id": ..., "ok": true, "result": {...}}
  {"type": "PING"}

Server -> client messages:
  {"type": "HELLO", "server_time": ..., "lease_sec": ...}
  {"type": "HEARTBEAT_ACK", "server_time": ..., "lease_sec": ...,
   "lease_until": ..., "commands": [...]}
  {"type": "COMMAND", "command": {"id": ..., "type": ..., "payload": {...}}}
  {"type": "ACK_OK", "command_id": ..., "status": ...}
  {"type": "PONG", "server_time": ...}
  {"type": "ERROR", "detail": ...}
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from gamenet.server.db import get_connection, utc_now_iso
from gamenet.server.realtime import hub, presence
from gamenet.server.repositories.agent_repository import AgentTokenRepository
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.agent_service import AgentService
from gamenet.server.services.errors import NotFound

router = APIRouter(prefix="/agent", tags=["agent"])


@router.websocket("/ws")
async def agent_ws(websocket: WebSocket, token: str = Query(...)) -> None:
    with get_connection() as conn:
        row = AgentTokenRepository(conn).find_valid(token)
    if row is None:
        await websocket.close(code=4401)
        return
    pc_id = row["pc_id"]
    agent_version = row.get("agent_version")
    await websocket.accept()
    now = time.time()
    hub.connect(pc_id, websocket, agent_version, now)
    with get_connection() as conn:
        lease_sec = SettingsRepository(conn).get_int("agent_lease_sec", 45)
    presence.record_heartbeat(
        pc_id, now, lease_sec, agent_version=agent_version,
        ip=websocket.client.host if websocket.client else None,
    )
    await websocket.send_json({
        "type": "HELLO",
        "server_time": utc_now_iso(),
        "lease_sec": lease_sec,
    })
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "HEARTBEAT":
                with get_connection() as conn:
                    resp = AgentService(conn).heartbeat(
                        {"pc_id": pc_id,
                         "agent_version": agent_version},
                        payload=msg.get("payload") or {},
                        ip=websocket.client.host
                        if websocket.client else None,
                    )
                await websocket.send_json(
                    {"type": "HEARTBEAT_ACK", **resp})
            elif mtype == "ACK":
                with get_connection() as conn:
                    try:
                        cmd = AgentService(conn).ack(
                            {"pc_id": pc_id},
                            msg.get("command_id") or "",
                            bool(msg.get("ok", True)),
                            msg.get("result"),
                        )
                    except NotFound:
                        await websocket.send_json(
                            {"type": "ERROR",
                             "detail": "Unknown command"})
                        continue
                await websocket.send_json(
                    {"type": "ACK_OK", "command_id": cmd["id"],
                     "status": cmd["status"]})
            elif mtype == "PING":
                await websocket.send_json(
                    {"type": "PONG", "server_time": utc_now_iso()})
            else:
                await websocket.send_json(
                    {"type": "ERROR",
                     "detail": f"Unknown message type: {mtype}"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.disconnect(pc_id, websocket)
        presence.mark_offline(pc_id)
