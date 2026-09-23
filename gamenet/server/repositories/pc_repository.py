import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class PcRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, *, device_code: str, display_name: str) -> dict:
        pc_id = f"PC-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO pcs (id, device_code, display_name, status,
                             created_at, updated_at)
            VALUES (?, ?, ?, 'OFFLINE', ?, ?)
            """,
            (pc_id, device_code, display_name, now, now),
        )
        self.add_history(pc_id=pc_id, from_status=None, to_status="OFFLINE",
                         reason="registered")
        return self.get(pc_id)

    def get(self, pc_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM pcs WHERE id = ?", (pc_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_device_code(self, device_code: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM pcs WHERE device_code = ?", (device_code,)
        ).fetchone()
        return dict(row) if row else None

    def list_pcs(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM pcs ORDER BY device_code"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_status(self, pc_id: str, status: str) -> dict | None:
        self._conn.execute(
            "UPDATE pcs SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_iso(), pc_id),
        )
        return self.get(pc_id)

    def set_display_name(self, pc_id: str, display_name: str) -> dict | None:
        self._conn.execute(
            "UPDATE pcs SET display_name = ?, updated_at = ? WHERE id = ?",
            (display_name, utc_now_iso(), pc_id),
        )
        return self.get(pc_id)

    def touch_seen(
        self, pc_id: str, *, agent_version: str | None = None
    ) -> None:
        now = utc_now_iso()
        if agent_version is not None:
            self._conn.execute(
                "UPDATE pcs SET last_seen_at = ?, agent_version = ?, updated_at = ? WHERE id = ?",
                (now, agent_version, now, pc_id),
            )
        else:
            self._conn.execute(
                "UPDATE pcs SET last_seen_at = ?, updated_at = ? WHERE id = ?",
                (now, now, pc_id),
            )

    def add_history(
        self,
        *,
        pc_id: str,
        from_status: str | None,
        to_status: str,
        reason: str | None = None,
        actor_user_id: str | None = None,
    ) -> None:
        hist_id = f"PHIST-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO pc_status_history (id, pc_id, from_status, to_status,
                                           reason, actor_user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hist_id, pc_id, from_status, to_status, reason,
                actor_user_id, utc_now_iso(),
            ),
        )

    def history(self, pc_id: str, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM pc_status_history WHERE pc_id = ? ORDER BY created_at DESC LIMIT ?",
            (pc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_device_secret(self, pc_id: str, secret_hash: str) -> None:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO device_credentials (pc_id, secret_hash, created_at, rotated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pc_id) DO UPDATE SET secret_hash = excluded.secret_hash,
                                              rotated_at = excluded.rotated_at
            """,
            (pc_id, secret_hash, now, now),
        )

    def get_device_secret_hash(self, pc_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT secret_hash FROM device_credentials WHERE pc_id = ?", (pc_id,)
        ).fetchone()
        return row["secret_hash"] if row else None
