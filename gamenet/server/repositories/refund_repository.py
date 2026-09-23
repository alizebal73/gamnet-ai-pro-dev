import sqlite3


class RefundRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, refund_id: str, sale_id: str, amount: int,
               method: str, reason: str, created_by: str,
               shift_id: str | None, created_at: str) -> dict:
        self._conn.execute(
            """INSERT INTO refunds (id, sale_id, amount, method, reason,
                                    created_by, shift_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (refund_id, sale_id, amount, method, reason, created_by,
             shift_id, created_at),
        )
        row = self._conn.execute(
            "SELECT * FROM refunds WHERE id = ?", (refund_id,)
        ).fetchone()
        return dict(row)

    def list_for_sale(self, sale_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM refunds WHERE sale_id = ? ORDER BY rowid",
            (sale_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def sum_for_sale(self, sale_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds "
            "WHERE sale_id = ?",
            (sale_id,),
        ).fetchone()
        return row["total"]
