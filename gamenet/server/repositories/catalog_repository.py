import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class CatalogRepository:
    """Packages + VIP plans (admin-managed catalog)."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ---- packages ----

    def create_package(
        self,
        *,
        name: str,
        duration_sec: int,
        price: int,
        bonus_sec: int = 0,
        validity_days: int | None = None,
    ) -> dict:
        pkg_id = f"PKG-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO packages (id, name, duration_sec, price, bonus_sec,
                                  validity_days, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (pkg_id, name, duration_sec, price, bonus_sec, validity_days, now, now),
        )
        return self.get_package(pkg_id)

    def get_package(self, pkg_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM packages WHERE id = ?", (pkg_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_packages(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM packages"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY duration_sec"
        return [dict(r) for r in self._conn.execute(sql).fetchall()]

    def update_package(self, pkg_id: str, fields: dict) -> dict | None:
        if not fields:
            return self.get_package(pkg_id)
        fields = dict(fields)
        fields["updated_at"] = utc_now_iso()
        if "active" in fields:
            fields["active"] = 1 if fields["active"] else 0
        assignments = ", ".join(f"{col} = ?" for col in fields)
        self._conn.execute(
            f"UPDATE packages SET {assignments} WHERE id = ?",
            (*fields.values(), pkg_id),
        )
        return self.get_package(pkg_id)

    # ---- VIP plans ----

    def create_vip_plan(
        self,
        *,
        name: str,
        duration_days: int,
        price: int,
        discount_pct: int = 0,
    ) -> dict:
        plan_id = f"VPLAN-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO vip_plans (id, name, duration_days, price, discount_pct,
                                   active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (plan_id, name, duration_days, price, discount_pct, now, now),
        )
        return self.get_vip_plan(plan_id)

    def get_vip_plan(self, plan_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM vip_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_vip_plans(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM vip_plans"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY duration_days"
        return [dict(r) for r in self._conn.execute(sql).fetchall()]

    def update_vip_plan(self, plan_id: str, fields: dict) -> dict | None:
        if not fields:
            return self.get_vip_plan(plan_id)
        fields = dict(fields)
        fields["updated_at"] = utc_now_iso()
        if "active" in fields:
            fields["active"] = 1 if fields["active"] else 0
        assignments = ", ".join(f"{col} = ?" for col in fields)
        self._conn.execute(
            f"UPDATE vip_plans SET {assignments} WHERE id = ?",
            (*fields.values(), plan_id),
        )
        return self.get_vip_plan(plan_id)
