import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class PricingRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        *,
        name: str,
        kind: str,
        duration_sec: int | None = None,
        price: int | None = None,
        factor_pct: int | None = None,
        pc_class: str | None = None,
        scope: str = "ANY",
        window_start_min: int | None = None,
        window_end_min: int | None = None,
        priority: int = 100,
        active: bool = True,
    ) -> dict:
        rule_id = f"PRICE-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO pricing_rules (
                id, name, kind, duration_sec, price, factor_pct, pc_class,
                scope, window_start_min, window_end_min, priority, active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id, name, kind, duration_sec, price, factor_pct, pc_class,
                scope, window_start_min, window_end_min, priority,
                1 if active else 0, now, now,
            ),
        )
        return self.get_by_id(rule_id)

    def get_by_id(self, rule_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM pricing_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_rules(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM pricing_rules"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY priority, name"
        return [dict(r) for r in self._conn.execute(sql).fetchall()]

    def update(self, rule_id: str, fields: dict) -> dict | None:
        if not fields:
            return self.get_by_id(rule_id)
        fields = dict(fields)
        fields["updated_at"] = utc_now_iso()
        if "active" in fields:
            fields["active"] = 1 if fields["active"] else 0
        assignments = ", ".join(f"{col} = ?" for col in fields)
        self._conn.execute(
            f"UPDATE pricing_rules SET {assignments} WHERE id = ?",
            (*fields.values(), rule_id),
        )
        return self.get_by_id(rule_id)
