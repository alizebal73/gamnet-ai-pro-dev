import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class PaymentRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        *,
        payment_id: str,
        sale_id: str,
        method: str,
        amount: int,
        tendered: int | None = None,
        status: str = "CREATED",
        provider: str,
        provider_ref: str | None = None,
        meta: str | None = None,
    ) -> dict:
        now = utc_now_iso()
        paid_at = now if status == "PAID" else None
        self._conn.execute(
            """
            INSERT INTO payments (id, sale_id, method, amount, tendered, status,
                                  provider, provider_ref, meta, created_at,
                                  updated_at, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payment_id, sale_id, method, amount, tendered, status,
                provider, provider_ref, meta, now, now, paid_at,
            ),
        )
        return self.get(payment_id)

    def get(self, payment_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_sale(self, sale_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM payments WHERE sale_id = ? ORDER BY created_at",
            (sale_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def sum_by_statuses(self, sale_id: str, statuses: list[str]) -> int:
        if not statuses:
            return 0
        placeholders = ", ".join("?" for _ in statuses)
        row = self._conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS s FROM payments "
            f"WHERE sale_id = ? AND status IN ({placeholders})",
            (sale_id, *statuses),
        ).fetchone()
        return int(row["s"])

    def set_status(
        self, payment_id: str, status: str, *, provider_ref: str | None = None
    ) -> dict | None:
        now = utc_now_iso()
        if provider_ref is not None:
            self._conn.execute(
                "UPDATE payments SET status = ?, provider_ref = ?, updated_at = ? WHERE id = ?",
                (status, provider_ref, now, payment_id),
            )
        else:
            self._conn.execute(
                "UPDATE payments SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, payment_id),
            )
        if status == "PAID":
            self._conn.execute(
                "UPDATE payments SET paid_at = COALESCE(paid_at, ?) WHERE id = ?",
                (now, payment_id),
            )
        return self.get(payment_id)

    def add_transaction(
        self,
        *,
        payment_id: str,
        kind: str,
        status: str,
        amount: int,
        provider_ref: str | None = None,
        message: str | None = None,
    ) -> dict:
        txn_id = f"PTXN-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO payment_transactions (id, payment_id, kind, status,
                                              provider_ref, amount, message,
                                              created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                txn_id, payment_id, kind, status, provider_ref, amount,
                message, utc_now_iso(),
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM payment_transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        return dict(row)

    def add_event(
        self,
        *,
        payment_id: str,
        from_status: str | None,
        to_status: str,
        reason: str | None = None,
    ) -> dict:
        event_id = f"PEVT-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO payment_events (id, payment_id, from_status, to_status,
                                        reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, payment_id, from_status, to_status, reason, utc_now_iso()),
        )
        row = self._conn.execute(
            "SELECT * FROM payment_events WHERE id = ?", (event_id,)
        ).fetchone()
        return dict(row)

    def list_events(self, payment_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM payment_events WHERE payment_id = ? ORDER BY created_at",
            (payment_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def unknown_queue(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT * FROM payments
            WHERE status IN ('PENDING', 'PROCESSING', 'UNKNOWN')
            ORDER BY created_at LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
