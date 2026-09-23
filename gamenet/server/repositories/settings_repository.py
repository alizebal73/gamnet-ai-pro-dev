import sqlite3

from gamenet.server.db import utc_now_iso


class SettingsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def get_int(self, key: str, default: int) -> int:
        raw = self.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def set(self, key: str, value: str) -> dict:
        self._conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utc_now_iso()),
        )
        row = self._conn.execute(
            "SELECT * FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return dict(row)

    def list_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM settings ORDER BY key").fetchall()
        return [dict(r) for r in rows]
