import sqlite3
import uuid


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class ShiftRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, shift_id: str, opened_by: str, opening_float: int,
               opened_at: str) -> dict:
        self._conn.execute(
            """INSERT INTO shifts (id, status, opened_by, opened_at, opening_float)
               VALUES (?, 'OPEN', ?, ?, ?)""",
            (shift_id, opened_by, opened_at, opening_float),
        )
        return self.get(shift_id)

    def get(self, shift_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM shifts WHERE id = ?", (shift_id,)
        ).fetchone()
        return dict(row) if row else None

    def current_open(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM shifts WHERE status = 'OPEN' LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def close(self, shift_id: str, *, closed_by: str, closed_at: str,
              expected: int, counted: int, variance: int,
              note: str | None) -> dict:
        self._conn.execute(
            """UPDATE shifts SET status = 'CLOSED', closed_by = ?,
                              closed_at = ?, expected_cash = ?,
                              counted_cash = ?, variance = ?, note = ?
               WHERE id = ?""",
            (closed_by, closed_at, expected, counted, variance, note,
             shift_id),
        )
        return self.get(shift_id)

    def add_movement(self, shift_id: str, kind: str, amount: int,
                     reason: str, created_by: str,
                     created_at: str) -> dict:
        movement_id = _new_id("CSH")
        self._conn.execute(
            """INSERT INTO cash_movements (id, shift_id, kind, amount, reason,
                                           created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (movement_id, shift_id, kind, amount, reason, created_by,
             created_at),
        )
        row = self._conn.execute(
            "SELECT * FROM cash_movements WHERE id = ?", (movement_id,)
        ).fetchone()
        return dict(row)

    def list_movements(self, shift_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM cash_movements WHERE shift_id = ? ORDER BY rowid",
            (shift_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def sum_movements(self, shift_id: str, kind: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cash_movements "
            "WHERE shift_id = ? AND kind = ?",
            (shift_id, kind),
        ).fetchone()
        return row["total"]

    def sum_cash_paid(self, shift_id: str) -> int:
        """PAID cash on live sales attached to this shift."""
        row = self._conn.execute(
            """SELECT COALESCE(SUM(p.amount), 0) AS total
               FROM payments p JOIN sales s ON s.id = p.sale_id
               WHERE s.shift_id = ? AND p.method = 'CASH'
                 AND p.status = 'PAID' AND s.status != 'CANCELLED'""",
            (shift_id,),
        ).fetchone()
        return row["total"]

    def list_shifts(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM shifts ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
