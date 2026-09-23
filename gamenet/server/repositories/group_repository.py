import sqlite3


class GroupRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_group(self, group_id: str, *, name: str | None,
                     shared_ends_at: str | None, created_by: str,
                     now: str) -> dict:
        self._conn.execute(
            """INSERT INTO session_groups (id, name, shared_ends_at,
                                           created_by, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (group_id, name, shared_ends_at, created_by, now),
        )
        return self.get_group(group_id)

    def get_group(self, group_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM session_groups WHERE id = ?", (group_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_open(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM session_groups WHERE status = 'OPEN' "
            "ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def close_group(self, group_id: str, now: str) -> dict:
        self._conn.execute(
            "UPDATE session_groups SET status = 'CLOSED', closed_at = ? "
            "WHERE id = ?",
            (now, group_id),
        )
        return self.get_group(group_id)

    def add_member(self, session_id: str, group_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET group_id = ? WHERE id = ?",
            (group_id, session_id),
        )

    def remove_member(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET group_id = NULL WHERE id = ?",
            (session_id,),
        )

    def members(self, group_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE group_id = ? ORDER BY created_at",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]
