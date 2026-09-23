import sqlite3


class CustomerAuthRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def find_customer(self, identifier: str) -> dict | None:
        identifier = (identifier or "").strip()
        if identifier.isdigit():
            row = self._conn.execute(
                "SELECT * FROM customers WHERE customer_number = ?",
                (int(identifier),),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM customers WHERE id = ?", (identifier,)
            ).fetchone()
        return dict(row) if row else None

    def get_auth(self, customer_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM customer_auth WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        return dict(row) if row else None

    def record_failure(self, customer_id: str, now: str,
                       locked_until: str | None) -> int:
        if locked_until:
            self._conn.execute(
                "UPDATE customer_auth SET failed_attempts = "
                "failed_attempts + 1, locked_until = ?, updated_at = ? "
                "WHERE customer_id = ?",
                (locked_until, now, customer_id),
            )
        else:
            self._conn.execute(
                "UPDATE customer_auth SET failed_attempts = "
                "failed_attempts + 1, updated_at = ? WHERE customer_id = ?",
                (now, customer_id),
            )
        row = self._conn.execute(
            "SELECT failed_attempts FROM customer_auth WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        return row["failed_attempts"]

    def reset_attempts(self, customer_id: str, now: str) -> None:
        self._conn.execute(
            "UPDATE customer_auth SET failed_attempts = 0, "
            "locked_until = NULL, updated_at = ? WHERE customer_id = ?",
            (now, customer_id),
        )

    def create_session(self, token_hash: str, customer_id: str,
                       created_at: str, expires_at: str,
                       ip: str | None) -> None:
        self._conn.execute(
            """INSERT INTO customer_sessions (token_hash, customer_id,
                                              created_at, expires_at, ip)
               VALUES (?, ?, ?, ?, ?)""",
            (token_hash, customer_id, created_at, expires_at, ip),
        )

    def find_session(self, token_hash: str, now: str) -> dict | None:
        row = self._conn.execute(
            """SELECT * FROM customer_sessions
               WHERE token_hash = ? AND revoked_at IS NULL
                 AND expires_at > ?""",
            (token_hash, now),
        ).fetchone()
        return dict(row) if row else None

    def revoke_session(self, token_hash: str, now: str) -> None:
        self._conn.execute(
            "UPDATE customer_sessions SET revoked_at = ? "
            "WHERE token_hash = ?",
            (now, token_hash),
        )
