import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class UserRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: str | None = None,
    ) -> dict:
        user_id = f"USER-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO users (id, username, password_hash, display_name, status,
                               failed_attempts, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'ACTIVE', 0, ?, ?)
            """,
            (user_id, username, password_hash, display_name, now, now),
        )
        return self.get_by_id(user_id)

    def get_by_id(self, user_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_username(self, username: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None

    def username_exists(self, username: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        return row is not None

    def role_exists(self, role_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM roles WHERE id = ?", (role_id,)
        ).fetchone()
        return row is not None

    def assign_role(self, user_id: str, role_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, assigned_at) VALUES (?, ?, ?)",
            (user_id, role_id, utc_now_iso()),
        )

    def get_roles(self, user_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT role_id FROM user_roles WHERE user_id = ? ORDER BY role_id",
            (user_id,),
        ).fetchall()
        return [row["role_id"] for row in rows]

    def get_permissions(self, user_id: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT rp.permission AS p
            FROM user_roles ur
            JOIN role_permissions rp ON rp.role_id = ur.role_id
            WHERE ur.user_id = ?
            ORDER BY p
            """,
            (user_id,),
        ).fetchall()
        return [row["p"] for row in rows]

    def increment_failed_attempts(self, user_id: str) -> int:
        self._conn.execute(
            "UPDATE users SET failed_attempts = failed_attempts + 1, updated_at = ? WHERE id = ?",
            (utc_now_iso(), user_id),
        )
        row = self._conn.execute(
            "SELECT failed_attempts FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return int(row["failed_attempts"])

    def reset_failed_attempts(self, user_id: str) -> None:
        self._conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?",
            (utc_now_iso(), user_id),
        )

    def lock_until(self, user_id: str, locked_until_iso: str) -> None:
        self._conn.execute(
            "UPDATE users SET locked_until = ?, updated_at = ? WHERE id = ?",
            (locked_until_iso, utc_now_iso(), user_id),
        )
