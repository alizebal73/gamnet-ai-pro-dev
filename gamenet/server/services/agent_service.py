"""Agent channel service: device auth, heartbeat, command queue (P2-1/2/3).

Master Spec: device auth separate from customer (135), heartbeat request
(328) / response (327), remote command execution with ACK (121-123),
reconnect sync (21-23).
Presence lives in memory (realtime.presence); the DB only stores tokens,
the command queue, and periodic last-seen flushes.

`emit_command` is the single choke point through which session lifecycle
events reach PCs: it queues the command and, if the PC has a live socket,
pushes it instantly (P2-3).
"""

from __future__ import annotations

import hmac
import json
import sqlite3
import time
from datetime import datetime, timezone

from gamenet.server.db import utc_now_iso
from gamenet.server.realtime import hub, presence
from gamenet.server.repositories.agent_repository import (
    AgentCommandRepository,
    AgentTokenRepository,
)
from gamenet.server.repositories.pc_repository import PcRepository
from gamenet.server.repositories.session_repository import SessionRepository
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.security.tokens import hash_token
from gamenet.server.services.errors import NotFound
from gamenet.shared.enums import AgentCommandType

# Throttle for the stale-command sweep: a heartbeat must stay cheap.
_last_expire_ts = 0.0
_EXPIRE_EVERY_SEC = 30.0


class AgentAuthError(Exception):
    pass


def emit_command(
    conn: sqlite3.Connection,
    pc_id: str | None,
    type: AgentCommandType | str,
    payload: dict | None = None,
    created_by: str | None = None,
) -> dict | None:
    """Queue a command for a PC and push it if a socket is live.

    NOTE: the push runs *before* the caller's commit, so an ACK that wins
    the race gets "Unknown command" — agents keep a pending-ACK list and
    retry on the next heartbeat, which makes this self-healing.
    """
    if not pc_id:
        return None
    if isinstance(type, str):
        type = AgentCommandType(type)
    ttl = SettingsRepository(conn).get_int("agent_command_ttl_sec", 300)
    row = AgentCommandRepository(conn).queue(pc_id, type, payload,
                                             created_by, ttl)
    pushed = hub.push_sync(pc_id, {
        "type": "COMMAND",
        "command": {"id": row["id"], "type": row["type"],
                    "payload": json.loads(row["payload_json"] or "{}")},
    })
    if pushed:
        AgentCommandRepository(conn).mark_sent([row["id"]])
        row = AgentCommandRepository(conn).get(row["id"])
    return row


class AgentService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._pcs = PcRepository(conn)
        self._tokens = AgentTokenRepository(conn)
        self._commands = AgentCommandRepository(conn)
        self._settings = SettingsRepository(conn)
        self._sessions = SessionRepository(conn)

    # -- device auth ----------------------------------------------------
    def authenticate(self, *, device_code: str, secret: str,
                     agent_version: str | None = None) -> dict:
        pc = self._pcs.get_by_device_code((device_code or "").strip())
        if pc is None:
            raise AgentAuthError("Unknown device")
        if pc["status"] == "RETIRED":
            raise AgentAuthError("PC is retired")
        stored = self._pcs.get_device_secret_hash(pc["id"])
        if not stored or not hmac.compare_digest(stored, hash_token(secret)):
            raise AgentAuthError("Bad device secret")
        ttl = self._settings.get_int("agent_token_ttl_hours", 24)
        row, token = self._tokens.issue(pc["id"], ttl, agent_version)
        return {"pc_id": pc["id"], "token": token,
                "expires_at": row["expires_at"]}

    # -- heartbeat ------------------------------------------------------
    def heartbeat(self, token_row: dict, *, payload: dict,
                  ip: str | None) -> dict:
        global _last_expire_ts
        now = time.time()
        if now - _last_expire_ts > _EXPIRE_EVERY_SEC:
            self._commands.expire_stale()
            _last_expire_ts = now
        lease_sec = self._settings.get_int("agent_lease_sec", 45)
        health = {k: payload.get(k) for k in
                  ("cpu_pct", "mem_pct", "disk_free_mb")
                  if payload.get(k) is not None}
        rec = presence.record_heartbeat(
            token_row["pc_id"], now, lease_sec,
            agent_version=payload.get("agent_version")
            or token_row.get("agent_version"),
            session_id=payload.get("session_id"),
            ip=ip, extra=health,
        )
        now_iso = utc_now_iso()
        pending = [c for c in
                   self._commands.pending_for_pc(token_row["pc_id"])
                   if c["expires_at"] > now_iso]
        self._commands.mark_sent([c["id"] for c in pending])
        lease_until = datetime.fromtimestamp(
            rec.lease_until, tz=timezone.utc).isoformat(timespec="seconds")
        live = self._sessions.active_for_pc(token_row["pc_id"])
        session_info = None
        if live is not None:
            session_info = {
                "id": live["id"], "status": live["status"],
                "customer_id": live["customer_id"],
                "pc_id": live["pc_id"],
                "started_at": live.get("started_at"),
            }
        return {
            "server_time": now_iso,
            "lease_sec": lease_sec,
            "lease_until": lease_until,
            "commands": [
                {"id": c["id"], "type": c["type"],
                 "payload": json.loads(c["payload_json"] or "{}")}
                for c in pending
            ],
            "session": session_info,
        }

    # -- command ACK (agent side) ---------------------------------------
    def ack(self, token_row: dict, command_id: str, ok: bool,
            result: dict | None) -> dict:
        try:
            cmd = self._commands.get(command_id)
        except KeyError:
            raise NotFound("Command not found")
        if cmd["pc_id"] != token_row["pc_id"]:
            raise NotFound("Command not found")
        return self._commands.ack(command_id, ok, result)

    # -- operator side --------------------------------------------------
    def queue_command(self, pc_id: str, type: str,
                      payload: dict | None,
                      created_by: str | None) -> dict:
        try:
            ctype = AgentCommandType(type)
        except ValueError:
            raise ValueError(f"Unknown command type: {type}")
        if self._pcs.get(pc_id) is None:
            raise NotFound("PC not found")
        ttl = self._settings.get_int("agent_command_ttl_sec", 300)
        return self._commands.queue(pc_id, ctype, payload, created_by, ttl)

    def list_commands(self, pc_id: str) -> list[dict]:
        if self._pcs.get(pc_id) is None:
            raise NotFound("PC not found")
        return self._commands.list_for_pc(pc_id)
