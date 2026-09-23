import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class SessionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        *,
        session_id: str,
        customer_id: str,
        pc_id: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO sessions (id, customer_id, pc_id, status, created_by,
                                  created_at, updated_at)
            VALUES (?, ?, ?, 'CREATED', ?, ?, ?)
            """,
            (session_id, customer_id, pc_id, created_by, now, now),
        )
        return self.get(session_id)

    def get(self, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def update(self, session_id: str, fields: dict) -> dict | None:
        fields = dict(fields)
        fields["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{col} = ?" for col in fields)
        self._conn.execute(
            f"UPDATE sessions SET {assignments} WHERE id = ?",
            (*fields.values(), session_id),
        )
        return self.get(session_id)

    def active_for_customer(self, customer_id: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT * FROM sessions WHERE customer_id = ?
              AND status IN ('AUTHORIZED', 'ACTIVE', 'PAUSED',
                             'INTERRUPTED', 'CONNECTION_LOST')
            """,
            (customer_id,),
        ).fetchone()
        return dict(row) if row else None

    def active_for_pc(self, pc_id: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT * FROM sessions WHERE pc_id = ?
              AND status IN ('AUTHORIZED', 'ACTIVE', 'PAUSED',
                             'INTERRUPTED', 'CONNECTION_LOST')
            """,
            (pc_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(
        self,
        *,
        customer_id: str | None = None,
        pc_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM sessions WHERE 1 = 1"
        params: list = []
        if customer_id:
            sql += " AND customer_id = ?"
            params.append(customer_id)
        if pc_id:
            sql += " AND pc_id = ?"
            params.append(pc_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def add_event(
        self,
        *,
        session_id: str,
        kind: str,
        from_status: str | None = None,
        to_status: str | None = None,
        pc_id: str | None = None,
        actor_user_id: str | None = None,
        reason: str | None = None,
    ) -> dict:
        event_id = f"SEVT-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO session_events (id, session_id, kind, from_status,
                                        to_status, pc_id, actor_user_id,
                                        reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, session_id, kind, from_status, to_status,
                pc_id, actor_user_id, reason, utc_now_iso(),
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM session_events WHERE id = ?", (event_id,)
        ).fetchone()
        return dict(row)

    def list_events(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_consumption(
        self,
        *,
        session_id: str,
        entitlement_id: str | None,
        seconds: int,
        period_start: str,
        period_end: str,
        kind: str,
    ) -> dict:
        con_id = f"SCON-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO session_consumptions (id, session_id, entitlement_id,
                                              seconds, period_start, period_end,
                                              kind, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                con_id, session_id, entitlement_id, seconds,
                period_start, period_end, kind, utc_now_iso(),
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM session_consumptions WHERE id = ?", (con_id,)
        ).fetchone()
        return dict(row)

    def list_consumptions(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM session_consumptions WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]
