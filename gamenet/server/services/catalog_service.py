import sqlite3

from gamenet.server.repositories.catalog_repository import CatalogRepository


class CatalogService:
    def __init__(self, conn: sqlite3.Connection):
        self._catalog = CatalogRepository(conn)

    # ---- packages ----

    def create_package(self, **fields) -> dict:
        self._validate_package(fields)
        return self._catalog.create_package(**fields)

    def update_package(self, pkg_id: str, fields: dict) -> dict | None:
        existing = self._catalog.get_package(pkg_id)
        if existing is None:
            return None
        merged = {**existing, **fields}
        self._validate_package(merged)
        allowed = {"name", "duration_sec", "price", "bonus_sec", "validity_days", "active"}
        return self._catalog.update_package(
            pkg_id, {k: v for k, v in fields.items() if k in allowed}
        )

    def get_package(self, pkg_id: str) -> dict | None:
        return self._catalog.get_package(pkg_id)

    def list_packages(self, active_only: bool = True) -> list[dict]:
        return self._catalog.list_packages(active_only=active_only)

    @staticmethod
    def _validate_package(fields: dict) -> None:
        if not (fields.get("name") or "").strip():
            raise ValueError("package name is required")
        if not (fields.get("duration_sec") or 0) > 0:
            raise ValueError("duration_sec must be positive")
        if (fields.get("price") or 0) <= 0:
            raise ValueError("price must be positive")
        if (fields.get("bonus_sec") or 0) < 0:
            raise ValueError("bonus_sec must be non-negative")
        validity = fields.get("validity_days")
        if validity is not None and validity <= 0:
            raise ValueError("validity_days must be positive")

    # ---- VIP plans ----

    def create_vip_plan(self, **fields) -> dict:
        self._validate_vip_plan(fields)
        return self._catalog.create_vip_plan(**fields)

    def update_vip_plan(self, plan_id: str, fields: dict) -> dict | None:
        existing = self._catalog.get_vip_plan(plan_id)
        if existing is None:
            return None
        merged = {**existing, **fields}
        self._validate_vip_plan(merged)
        allowed = {"name", "duration_days", "price", "discount_pct", "active"}
        return self._catalog.update_vip_plan(
            plan_id, {k: v for k, v in fields.items() if k in allowed}
        )

    def get_vip_plan(self, plan_id: str) -> dict | None:
        return self._catalog.get_vip_plan(plan_id)

    def list_vip_plans(self, active_only: bool = True) -> list[dict]:
        return self._catalog.list_vip_plans(active_only=active_only)

    @staticmethod
    def _validate_vip_plan(fields: dict) -> None:
        if not (fields.get("name") or "").strip():
            raise ValueError("plan name is required")
        if not (fields.get("duration_days") or 0) > 0:
            raise ValueError("duration_days must be positive")
        if (fields.get("price") or 0) <= 0:
            raise ValueError("price must be positive")
        pct = fields.get("discount_pct") or 0
        if not 0 <= pct <= 100:
            raise ValueError("discount_pct must be 0..100")
