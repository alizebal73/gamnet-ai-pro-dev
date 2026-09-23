import sqlite3


class ReservationRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, res_id: str, *, customer_id: str, pc_id: str,
               starts_at: str, ends_at: str, note: str | None,
               created_by: str, now: str) -> dict:
        self._conn.execute(
            """INSERT INTO reservations (id, customer_id, pc_id, starts_at,
                                         ends_at, note, created_by,
                                         created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (res_id, customer_id, pc_id, starts_at, ends_at, note,
             created_by, now, now),
        )
        return self.get(res_id)

    def get(self, res_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM reservations WHERE id = ?", (res_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_reservations(self, *, pc_id: str | None = None,
             customer_id: str | None = None,
             status: str | None = None,
             frm: str | None = None, to: str | None = None,
             limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM reservations WHERE 1 = 1"
        params: list = []
        if pc_id:
            sql += " AND pc_id = ?"
            params.append(pc_id)
        if customer_id:
            sql += " AND customer_id = ?"
            params.append(customer_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if frm:
            sql += " AND ends_at > ?"
            params.append(frm)
        if to:
            sql += " AND starts_at < ?"
            params.append(to)
        sql += " ORDER BY starts_at LIMIT ?"
        params.append(limit)
        return [dict(r)
                for r in self._conn.execute(sql, params).fetchall()]

    def overlapping(self, pc_id: str, starts_at: str, ends_at: str,
                    exclude: str | None = None) -> list[dict]:
        sql = """SELECT * FROM reservations
                 WHERE pc_id = ? AND status = 'BOOKED'
                   AND NOT (ends_at <= ? OR starts_at >= ?)"""
        params: list = [pc_id, starts_at, ends_at]
        if exclude:
            sql += " AND id != ?"
            params.append(exclude)
        return [dict(r)
                for r in self._conn.execute(sql, params).fetchall()]

    def set_status(self, res_id: str, status: str, now: str,
                   cancel_reason: str | None = None) -> dict:
        self._conn.execute(
            "UPDATE reservations SET status = ?, updated_at = ?, "
            "cancel_reason = COALESCE(?, cancel_reason) WHERE id = ?",
            (status, now, cancel_reason, res_id),
        )
        return self.get(res_id)

    def expire_past(self, now: str) -> int:
        cur = self._conn.execute(
            "UPDATE reservations SET status = 'EXPIRED', updated_at = ? "
            "WHERE status = 'BOOKED' AND ends_at <= ?",
            (now, now),
        )
        return cur.rowcount
