import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class SaleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_sale(
        self,
        *,
        sale_id: str,
        customer_id: str,
        operator_user_id: str,
        subtotal: int,
        discount_pct: int,
        discount_amount: int,
        discount_reason: str | None,
        total: int,
    ) -> dict:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO sales (id, customer_id, operator_user_id, status, subtotal,
                               discount_pct, discount_amount, discount_reason,
                               total, created_at, updated_at)
            VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sale_id, customer_id, operator_user_id, subtotal, discount_pct,
                discount_amount, discount_reason, total, now, now,
            ),
        )
        return self.get_sale(sale_id)

    def get_sale(self, sale_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sales WHERE id = ?", (sale_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sales(
        self, *, customer_id: str | None = None, status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM sales WHERE 1 = 1"
        params: list = []
        if customer_id:
            sql += " AND customer_id = ?"
            params.append(customer_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def set_status(
        self, sale_id: str, status: str, *, cancel_reason: str | None = None
    ) -> dict | None:
        now = utc_now_iso()
        extra = ""
        params: list = [status, now]
        if status == "CONFIRMED":
            extra = ", confirmed_at = ?"
            params.append(now)
        elif status == "CANCELLED":
            extra = ", cancelled_at = ?, cancel_reason = ?"
            params.extend([now, cancel_reason])
        params.append(sale_id)
        self._conn.execute(
            f"UPDATE sales SET status = ?, updated_at = ?{extra} WHERE id = ?",
            params,
        )
        return self.get_sale(sale_id)

    def add_item(
        self,
        *,
        sale_id: str,
        kind: str,
        label: str,
        qty: int,
        unit_price: int,
        total_price: int,
        duration_sec: int | None = None,
        pc_class: str | None = None,
        ref_id: str | None = None,
        price_snapshot: str,
    ) -> dict:
        item_id = f"SITEM-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO sale_items (id, sale_id, kind, label, qty, unit_price,
                                    total_price, duration_sec, pc_class, ref_id,
                                    price_snapshot, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, sale_id, kind, label, qty, unit_price, total_price,
                duration_sec, pc_class, ref_id, price_snapshot, utc_now_iso(),
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM sale_items WHERE id = ?", (item_id,)
        ).fetchone()
        return dict(row)

    def list_items(self, sale_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY created_at",
            (sale_id,),
        ).fetchall()
        return [dict(r) for r in rows]
