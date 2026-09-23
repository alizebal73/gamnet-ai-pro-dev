import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from gamenet.server.db import utc_now_iso
from gamenet.shared.enums import AgentCommandStatus, AgentCommandType


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class AgentTokenRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def issue(self, pc_id: str, ttl_hours: int,
              agent_version: str | None = None) -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        row = {
            "id": _new_id("AGT"),
            "token_hash": token_hash,
            "pc_id": pc_id,
            "issued_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(timespec="seconds"),
            "agent_version": agent_version,
        }
        self._conn.execute(
            """INSERT INTO agent_tokens (id, token_hash, pc_id, issued_at, expires_at, agent_version)
               VALUES (:id, :token_hash, :pc_id, :issued_at, :expires_at, :agent_version)""",
            row,
        )
        saved = self._conn.execute(
            "SELECT * FROM agent_tokens WHERE id = ?", (row["id"],)
        ).fetchone()
        return dict(saved), token

    def find_valid(self, token: str) -> dict | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        row = self._conn.execute(
            """SELECT * FROM agent_tokens
               WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?""",
            (token_hash, utc_now_iso()),
        ).fetchone()
        return dict(row) if row else None

    def touch_seen(self, token_id: str) -> None:
        self._conn.execute(
            "UPDATE agent_tokens SET last_seen_at = ? WHERE id = ?",
            (utc_now_iso(), token_id),
        )

    def revoke_for_pc(self, pc_id: str) -> int:
        cur = self._conn.execute(
            "UPDATE agent_tokens SET revoked_at = ? WHERE pc_id = ? AND revoked_at IS NULL",
            (utc_now_iso(), pc_id),
        )
        return cur.rowcount


class AgentCommandRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def queue(self, pc_id: str, type: AgentCommandType | str,
              payload: dict | None = None, created_by: str | None = None,
              ttl_sec: int = 300) -> dict:
        now = datetime.now(timezone.utc)
        row = {
            "id": _new_id("CMD"),
            "pc_id": pc_id,
            "type": type.value if isinstance(type, AgentCommandType) else type,
            "payload_json": json.dumps(payload or {}),
            "status": AgentCommandStatus.PENDING.value,
            "created_by": created_by,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(seconds=ttl_sec)).isoformat(timespec="seconds"),
        }
        self._conn.execute(
            """INSERT INTO agent_commands (id, pc_id, type, payload_json, status, created_by, created_at, expires_at)
               VALUES (:id, :pc_id, :type, :payload_json, :status, :created_by, :created_at, :expires_at)""",
            row,
        )
        return self.get(row["id"])

    def get(self, command_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM agent_commands WHERE id = ?", (command_id,)
        ).fetchone()
        if row is None:
            raise KeyError(command_id)
        return dict(row)

    def pending_for_pc(self, pc_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM agent_commands WHERE pc_id = ? AND status = 'PENDING'
               ORDER BY rowid LIMIT ?""",
            (pc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, ids: list[str]) -> None:
        if not ids:
            return
        self._conn.execute(
            f"UPDATE agent_commands SET status = 'SENT', sent_at = ? WHERE id IN ({','.join('?' * len(ids))})",
            [utc_now_iso(), *ids],
        )

    def ack(self, command_id: str, ok: bool, result: dict | None = None) -> dict:
        try:
            cmd = self.get(command_id)
        except KeyError:
            raise ValueError("Unknown command")
        if cmd["status"] in ("ACKED", "FAILED", "EXPIRED"):
            return cmd
        status = ("ACKED" if ok else "FAILED")
        self._conn.execute(
            "UPDATE agent_commands SET status = ?, acked_at = ?, result_json = ? WHERE id = ?",
            (status, utc_now_iso(), json.dumps(result or {}), command_id),
        )
        return self.get(command_id)

    def expire_stale(self) -> int:
        cur = self._conn.execute(
            "UPDATE agent_commands SET status = 'EXPIRED' WHERE status IN ('PENDING','SENT') AND expires_at <= ?",
            (utc_now_iso(),),
        )
        return cur.rowcount

    def list_for_pc(self, pc_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_commands WHERE pc_id = ? ORDER BY rowid DESC LIMIT ?",
            (pc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
