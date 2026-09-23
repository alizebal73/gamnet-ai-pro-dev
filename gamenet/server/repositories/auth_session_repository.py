import sqlite3

from gamenet.server.db import utc_now_iso


class AuthSessionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        *,
        token_hash: str,
        user_id: str,
        expires_at: str,
        created_ip: str | None = None,
    ) -> dict:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at, created_ip)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, user_id, now, expires_at, created_ip),
        )
        row = self._conn.execute(
            "SELECT * FROM auth_sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return dict(row)

    def get_valid(self, token_hash: str, now_iso: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT * FROM auth_sessions
            WHERE token_hash = ?
              AND revoked_at IS NULL
              AND expires_at > ?
            """,
            (token_hash, now_iso),
        ).fetchone()
        return dict(row) if row else None

    def revoke(self, token_hash: str) -> None:
        self._conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (utc_now_iso(), token_hash),
        )

    def revoke_all_for_user(self, user_id: str) -> None:
        self._conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (utc_now_iso(), user_id),
        )
