"""Snack/bar inventory (P3-3). Append-only stock ledger; stock can never
go negative; FOOD sales decrement at confirm time via `sell()`."""

import sqlite3

from gamenet.server.db import utc_now_iso
from gamenet.server.repositories.inventory_repository import (
    InventoryRepository,
)
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number


class InventoryService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._items = InventoryRepository(conn)

    def create_item(self, *, sku: str, name: str, unit_price: int,
                    low_stock_at: int = 0) -> dict:
        sku, name = (sku or "").strip(), (name or "").strip()
        if not sku:
            raise ValueError("sku is required")
        if not name:
            raise ValueError("name is required")
        if unit_price < 0:
            raise ValueError("unit_price cannot be negative")
        if low_stock_at < 0:
            raise ValueError("low_stock_at cannot be negative")
        try:
            item = self._items.create(
                next_number(self._conn, name="inventory", prefix="INV"),
                sku=sku, name=name, unit_price=unit_price,
                low_stock_at=low_stock_at, now=utc_now_iso(),
            )
        except ValueError as exc:
            raise InvalidState(str(exc))
        return self._enrich(item)

    def update_item(self, item_id: str, *, name: str | None = None,
                    unit_price: int | None = None,
                    low_stock_at: int | None = None) -> dict:
        item = self._require(item_id)
        fields: dict = {}
        if name is not None:
            if not name.strip():
                raise ValueError("name cannot be empty")
            fields["name"] = name.strip()
        if unit_price is not None:
            if unit_price < 0:
                raise ValueError("unit_price cannot be negative")
            fields["unit_price"] = unit_price
        if low_stock_at is not None:
            if low_stock_at < 0:
                raise ValueError("low_stock_at cannot be negative")
            fields["low_stock_at"] = low_stock_at
        fields["updated_at"] = utc_now_iso()
        return self._enrich(self._items.update(item["id"], fields))

    def set_archived(self, item_id: str, archived: bool) -> dict:
        self._require(item_id)
        updated = self._items.update(item_id, {
            "status": "ARCHIVED" if archived else "ACTIVE",
            "updated_at": utc_now_iso(),
        })
        return self._enrich(updated)

    def receive(self, item_id: str, *, qty: int,
                created_by: str | None = None,
                reason: str | None = None) -> dict:
        self._require(item_id)
        if qty <= 0:
            raise ValueError("qty must be positive")
        updated = self._items.apply_delta(
            item_id, qty, kind="RECEIVE", reason=reason,
            created_by=created_by, now=utc_now_iso(),
        )
        return self._enrich(updated)

    def adjust(self, item_id: str, *, delta: int, reason: str,
               created_by: str | None = None) -> dict:
        item = self._require(item_id)
        if delta == 0:
            raise ValueError("delta must be non-zero")
        if not (reason or "").strip():
            raise ValueError("adjust reason is required")
        if item["stock_qty"] + delta < 0:
            raise InvalidState("adjustment would make stock negative")
        updated = self._items.apply_delta(
            item_id, delta, kind="ADJUST", reason=reason.strip(),
            created_by=created_by, now=utc_now_iso(),
        )
        return self._enrich(updated)

    def sell(self, item_id: str, *, qty: int, sale_id: str,
             sale_item_id: str,
             created_by: str | None = None) -> dict:
        """Decrement stock for a confirmed sale (activation path)."""
        item = self._items.get(item_id)
        if item is None or item["status"] != "ACTIVE":
            raise InvalidState(f"inventory item {item_id} unavailable")
        if item["stock_qty"] < qty:
            raise InvalidState(
                f"insufficient stock for {item['name']} "
                f"({item['stock_qty']} < {qty})")
        updated = self._items.apply_delta(
            item_id, -qty, kind="SELL", ref_type="sale", ref_id=sale_id,
            reason=f"sale item {sale_item_id}", created_by=created_by,
            now=utc_now_iso(),
        )
        return self._enrich(updated)

    def get(self, item_id: str) -> dict:
        return self._enrich(self._require(item_id))

    def list_items(self, *, status: str | None = None,
                   low_only: bool = False) -> list[dict]:
        return [self._enrich(i) for i in
                self._items.list_items(status=status, low_only=low_only)]

    def ledger(self, item_id: str, limit: int = 200) -> list[dict]:
        self._require(item_id)
        return self._items.ledger_for_item(item_id, limit)

    def _require(self, item_id: str) -> dict:
        item = self._items.get(item_id)
        if item is None:
            raise NotFound("Inventory item not found")
        return item

    @staticmethod
    def _enrich(item: dict) -> dict:
        item = dict(item)
        item["low_stock"] = (
            item["low_stock_at"] > 0
            and item["stock_qty"] <= item["low_stock_at"]
        )
        return item
