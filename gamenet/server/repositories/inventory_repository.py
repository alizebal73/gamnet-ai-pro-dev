import sqlite3
import uuid


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class InventoryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, item_id: str, *, sku: str, name: str,
               unit_price: int, low_stock_at: int, now: str) -> dict:
        try:
            self._conn.execute(
                """INSERT INTO inventory_items (id, sku, name, unit_price,
                                                low_stock_at, created_at,
                                                updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (item_id, sku, name, unit_price, low_stock_at, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"sku '{sku}' already exists")
        return self.get(item_id)

    def get(self, item_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM inventory_items WHERE id = ?", (item_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_items(self, *, status: str | None = None,
                   low_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM inventory_items WHERE 1 = 1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if low_only:
            sql += " AND low_stock_at > 0 AND stock_qty <= low_stock_at"
        sql += " ORDER BY name"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def update(self, item_id: str, fields: dict) -> dict | None:
        if not fields:
            return self.get(item_id)
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE inventory_items SET {cols} WHERE id = ?",
            (*fields.values(), item_id),
        )
        return self.get(item_id)

    def apply_delta(self, item_id: str, delta: int, *, kind: str,
                    ref_type: str | None = None,
                    ref_id: str | None = None,
                    reason: str | None = None,
                    created_by: str | None = None, now: str) -> dict:
        item = self.get(item_id)
        new_qty = item["stock_qty"] + delta
        self._conn.execute(
            "UPDATE inventory_items SET stock_qty = ?, updated_at = ? "
            "WHERE id = ?",
            (new_qty, now, item_id),
        )
        entry_id = _new_id("SLED")
        self._conn.execute(
            """INSERT INTO stock_ledger (id, item_id, delta, balance_after,
                                         kind, ref_type, ref_id, reason,
                                         created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, item_id, delta, new_qty, kind, ref_type, ref_id,
             reason, created_by, now),
        )
        return self.get(item_id)

    def ledger_for_item(self, item_id: str, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM stock_ledger WHERE item_id = ? "
            "ORDER BY rowid DESC LIMIT ?",
            (item_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
