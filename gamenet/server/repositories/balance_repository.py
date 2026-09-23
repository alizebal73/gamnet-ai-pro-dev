import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class BalanceRepository:
    """Append-only customer money ledger (Master Spec 85-87)."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def balance_of(self, customer_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT balance_after FROM customer_balance_ledger
            WHERE customer_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (customer_id,),
        ).fetchone()
        return int(row["balance_after"]) if row else 0

    def append(
        self,
        *,
        customer_id: str,
        amount: int,
        kind: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        reason: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        balance_after = self.balance_of(customer_id) + amount
        entry_id = f"BLED-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO customer_balance_ledger (id, customer_id, amount,
                                                 balance_after, kind, ref_type,
                                                 ref_id, reason, created_by,
                                                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id, customer_id, amount, balance_after, kind,
                ref_type, ref_id, reason, created_by, utc_now_iso(),
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM customer_balance_ledger WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(row)

    def list_for_customer(self, customer_id: str, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT * FROM customer_balance_ledger
            WHERE customer_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?
            """,
            (customer_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
