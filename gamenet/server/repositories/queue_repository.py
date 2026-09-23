import sqlite3


class QueueRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, entry_id: str, *, customer_id: str,
               pc_id: str | None, priority: int, note: str | None,
               created_by: str, now: str) -> dict:
        self._conn.execute(
            """INSERT INTO queue_entries (id, customer_id, pc_id, priority,
                                          note, created_by, created_at,
                                          updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, customer_id, pc_id, priority, note, created_by,
             now, now),
        )
        return self.get(entry_id)

    def get(self, entry_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM queue_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_active(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM queue_entries "
            "WHERE status IN ('WAITING', 'CALLED') ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def waiting_for_customer(self, customer_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM queue_entries WHERE customer_id = ? "
            "AND status IN ('WAITING', 'CALLED') LIMIT 1",
            (customer_id,),
        ).fetchone()
        return dict(row) if row else None

    def set_status(self, entry_id: str, status: str, now: str,
                   called: bool = False) -> dict:
        if called:
            self._conn.execute(
                "UPDATE queue_entries SET status = ?, called_at = ?, "
                "updated_at = ? WHERE id = ?",
                (status, now, now, entry_id),
            )
        else:
            self._conn.execute(
                "UPDATE queue_entries SET status = ?, updated_at = ? "
                "WHERE id = ?",
                (status, now, entry_id),
            )
        return self.get(entry_id)

    def expire_older_than(self, cutoff: str, now: str) -> int:
        cur = self._conn.execute(
            "UPDATE queue_entries SET status = 'EXPIRED', updated_at = ? "
            "WHERE status IN ('WAITING', 'CALLED') AND created_at <= ?",
            (now, cutoff),
        )
        return cur.rowcount
