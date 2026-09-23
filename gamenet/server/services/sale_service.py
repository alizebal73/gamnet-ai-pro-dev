import json
import sqlite3

from gamenet.server.repositories.catalog_repository import CatalogRepository
from gamenet.server.repositories.customer_repository import CustomerRepository
from gamenet.server.repositories.payment_repository import PaymentRepository
from gamenet.server.repositories.sale_repository import SaleRepository
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound, PermissionDenied
from gamenet.server.services.numbering import next_number
from gamenet.server.services.pricing_service import PricingService
from gamenet.shared.enums import PaymentStatus, SaleItemKind, SaleStatus

# Item kinds priced server-side. ACCESSORY still needs a catalog (later).
SUPPORTED_KINDS = {
    SaleItemKind.TIME.value, SaleItemKind.RECHARGE.value,
    SaleItemKind.VIP.value, SaleItemKind.PACKAGE.value,
    SaleItemKind.FOOD.value,
}


class SaleService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._sales = SaleRepository(conn)
        self._payments = PaymentRepository(conn)
        self._customers = CustomerRepository(conn)
        self._settings = SettingsRepository(conn)
        self._pricing = PricingService(conn)
        self._catalog = CatalogRepository(conn)

    def detail(self, sale_id: str) -> dict:
        sale = self._sales.get_sale(sale_id)
        if sale is None:
            raise NotFound("Sale not found")
        from gamenet.server.repositories.refund_repository import (
            RefundRepository,
        )

        sale["items"] = self._sales.list_items(sale_id)
        sale["payments"] = self._payments.list_by_sale(sale_id)
        refunds = RefundRepository(self._conn)
        sale["refunds"] = refunds.list_for_sale(sale_id)
        sale["refunded_total"] = refunds.sum_for_sale(sale_id)
        return sale

    def create_draft(
        self,
        *,
        customer_id: str,
        items: list[dict],
        discount_pct: int = 0,
        discount_reason: str | None = None,
        auth: AuthContext,
    ) -> dict:
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFound("Customer not found")
        if customer["status"] != "ACTIVE":
            raise InvalidState("Customer is not active")
        if not items:
            raise ValueError("Sale needs at least one item")
        if not 0 <= discount_pct <= 100:
            raise ValueError("discount_pct must be 0..100")
        if discount_pct > 0 and not (discount_reason or "").strip():
            raise ValueError("discount_reason is required when discount_pct > 0")
        self._check_discount_permission(discount_pct, auth)

        priced = [self._price_item(raw, index) for index, raw in enumerate(items)]
        subtotal = sum(p["total_price"] for p in priced)
        discount_amount = (subtotal * discount_pct + 50) // 100
        total = subtotal - discount_amount

        sale_id = next_number(self._conn, name="sale", prefix="SALE")
        self._sales.create_sale(
            sale_id=sale_id,
            customer_id=customer_id,
            operator_user_id=auth.user_id,
            subtotal=subtotal,
            discount_pct=discount_pct,
            discount_amount=discount_amount,
            discount_reason=(discount_reason or "").strip() or None,
            total=total,
        )
        for p in priced:
            self._sales.add_item(sale_id=sale_id, **p)
        return self.detail(sale_id)

    def confirm(self, sale_id: str, *, created_by: str | None = None) -> dict:
        from gamenet.server.services.activation_service import grant_for_sale

        sale = self._sales.get_sale(sale_id)
        if sale is None:
            raise NotFound("Sale not found")
        if sale["status"] == SaleStatus.CONFIRMED.value:
            return self.detail(sale_id)  # naturally idempotent
        if sale["status"] != SaleStatus.DRAFT.value:
            raise InvalidState(f"Sale is {sale['status']}, cannot confirm")
        paid = self._payments.sum_by_statuses(sale_id, [PaymentStatus.PAID.value])
        if paid != sale["total"]:
            raise InvalidState(
                f"Paid {paid} of {sale['total']}; sale is not fully paid"
            )
        self._sales.set_status(sale_id, SaleStatus.CONFIRMED.value)
        # Attach to the open shift (if any) so the drawer stays complete.
        from gamenet.server.repositories.shift_repository import (
            ShiftRepository,
        )

        open_shift = ShiftRepository(self._conn).current_open()
        if open_shift is not None:
            self._sales.attach_shift(sale_id, open_shift["id"])
        items = self._sales.list_items(sale_id)
        grant_for_sale(self._conn, sale, items, created_by=created_by)
        return self.detail(sale_id)

    def cancel(self, sale_id: str, *, reason: str) -> dict:
        sale = self._sales.get_sale(sale_id)
        if sale is None:
            raise NotFound("Sale not found")
        if sale["status"] != SaleStatus.DRAFT.value:
            raise InvalidState(f"Sale is {sale['status']}, cannot cancel")
        if not (reason or "").strip():
            raise ValueError("cancel reason is required")
        settled = self._payments.sum_by_statuses(sale_id, [PaymentStatus.PAID.value])
        if settled > 0:
            raise InvalidState(
                "Sale has settled payments; cancel is forbidden, refund instead"
            )
        for payment in self._payments.list_by_sale(sale_id):
            if payment["status"] in (
                PaymentStatus.CREATED.value,
                PaymentStatus.PENDING.value,
                PaymentStatus.PROCESSING.value,
                PaymentStatus.UNKNOWN.value,
            ):
                self._payments.set_status(payment["id"], PaymentStatus.CANCELLED.value)
                self._payments.add_event(
                    payment_id=payment["id"],
                    from_status=payment["status"],
                    to_status=PaymentStatus.CANCELLED.value,
                    reason="sale cancelled",
                )
        self._sales.set_status(
            sale_id, SaleStatus.CANCELLED.value, cancel_reason=reason.strip()
        )
        return self.detail(sale_id)

    def _check_discount_permission(self, discount_pct: int, auth: AuthContext) -> None:
        if discount_pct <= 0:
            return
        roles = set(auth.roles)
        if roles & {"owner", "manager"}:
            return  # unlimited
        limit = self._settings.get_int("operator_max_discount_pct", 10)
        if discount_pct > limit:
            raise PermissionDenied(
                f"Discount {discount_pct}% exceeds your limit of {limit}%"
            )

    def _price_item(self, raw: dict, index: int) -> dict:
        kind = raw.get("kind")
        if kind not in SUPPORTED_KINDS:
            raise ValueError(
                f"item {index}: kind '{kind}' is not supported yet "
                f"(supported: {sorted(SUPPORTED_KINDS)})"
            )
        if kind == SaleItemKind.TIME.value:
            duration_sec = raw.get("duration_sec") or 0
            if duration_sec <= 0:
                raise ValueError(f"item {index}: TIME needs duration_sec > 0")
            if raw.get("qty", 1) != 1:
                raise ValueError(f"item {index}: TIME qty must be 1")
            quote = self._pricing.quote(
                duration_sec=duration_sec, pc_class=raw.get("pc_class")
            )
            minutes = duration_sec // 60
            return {
                "kind": kind,
                "label": raw.get("label") or f"Play time {minutes} min",
                "qty": 1,
                "unit_price": quote.total,
                "total_price": quote.total,
                "duration_sec": duration_sec,
                "pc_class": raw.get("pc_class"),
                "ref_id": None,
                "price_snapshot": json.dumps(quote.snapshot, ensure_ascii=True),
            }
        if kind == SaleItemKind.VIP.value:
            return self._price_vip_item(raw, index)
        if kind == SaleItemKind.PACKAGE.value:
            return self._price_package_item(raw, index)
        if kind == SaleItemKind.FOOD.value:
            return self._price_food_item(raw, index)
        # RECHARGE: the amount IS the value granted; operator enters it.
        unit_price = raw.get("unit_price") or 0
        if unit_price <= 0:
            raise ValueError(f"item {index}: RECHARGE needs unit_price > 0")
        if raw.get("qty", 1) != 1:
            raise ValueError(f"item {index}: RECHARGE qty must be 1")
        snapshot = {
            "kind": "RECHARGE", "amount": unit_price, "currency_unit": "RIAL",
            "note": "operator-entered recharge amount",
        }
        return {
            "kind": kind,
            "label": raw.get("label") or "Balance recharge",
            "qty": 1,
            "unit_price": unit_price,
            "total_price": unit_price,
            "duration_sec": None,
            "pc_class": None,
            "ref_id": None,
            "price_snapshot": json.dumps(snapshot, ensure_ascii=True),
        }

    def _price_vip_item(self, raw: dict, index: int) -> dict:
        plan_id = raw.get("ref_id")
        if not plan_id:
            raise ValueError(f"item {index}: VIP needs ref_id (plan id)")
        plan = self._catalog.get_vip_plan(plan_id)
        if plan is None or not plan["active"]:
            raise ValueError(f"item {index}: VIP plan unavailable")
        if raw.get("qty", 1) != 1:
            raise ValueError(f"item {index}: VIP qty must be 1")
        # Server-side price: client-supplied unit_price is ignored (Spec 197).
        snapshot = {
            "kind": "VIP", "plan_id": plan["id"], "plan_name": plan["name"],
            "duration_days": plan["duration_days"], "price": plan["price"],
            "discount_pct": plan["discount_pct"], "currency_unit": "RIAL",
        }
        return {
            "kind": SaleItemKind.VIP.value,
            "label": raw.get("label") or f"VIP {plan['name']}",
            "qty": 1,
            "unit_price": plan["price"],
            "total_price": plan["price"],
            "duration_sec": None,
            "pc_class": None,
            "ref_id": plan["id"],
            "price_snapshot": json.dumps(snapshot, ensure_ascii=True),
        }

    def _price_package_item(self, raw: dict, index: int) -> dict:
        pkg_id = raw.get("ref_id")
        if not pkg_id:
            raise ValueError(f"item {index}: PACKAGE needs ref_id (package id)")
        pkg = self._catalog.get_package(pkg_id)
        if pkg is None or not pkg["active"]:
            raise ValueError(f"item {index}: package unavailable")
        if raw.get("qty", 1) != 1:
            raise ValueError(f"item {index}: PACKAGE qty must be 1")
        snapshot = {
            "kind": "PACKAGE", "package_id": pkg["id"],
            "package_name": pkg["name"], "duration_sec": pkg["duration_sec"],
            "bonus_sec": pkg["bonus_sec"], "price": pkg["price"],
            "validity_days": pkg["validity_days"], "currency_unit": "RIAL",
        }
        return {
            "kind": SaleItemKind.PACKAGE.value,
            "label": raw.get("label") or f"Package {pkg['name']}",
            "qty": 1,
            "unit_price": pkg["price"],
            "total_price": pkg["price"],
            "duration_sec": pkg["duration_sec"],
            "pc_class": None,
            "ref_id": pkg["id"],
            "price_snapshot": json.dumps(snapshot, ensure_ascii=True),
        }

    def _price_food_item(self, raw: dict, index: int) -> dict:
        from gamenet.server.repositories.inventory_repository import (
            InventoryRepository,
        )

        item_id = raw.get("ref_id")
        if not item_id:
            raise ValueError(
                f"item {index}: FOOD needs ref_id (inventory item id)")
        qty = raw.get("qty", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ValueError(
                f"item {index}: FOOD qty must be a positive integer")
        item = InventoryRepository(self._conn).get(item_id)
        if item is None or item["status"] != "ACTIVE":
            raise ValueError(f"item {index}: food item unavailable")
        if item["stock_qty"] < qty:
            raise InvalidState(
                f"item {index}: insufficient stock for {item['name']} "
                f"({item['stock_qty']} < {qty})"
            )
        # Server-side price: client-supplied unit_price is ignored.
        snapshot = {
            "kind": "FOOD", "item_id": item["id"], "sku": item["sku"],
            "item_name": item["name"], "unit_price": item["unit_price"],
            "qty": qty, "currency_unit": "RIAL",
        }
        return {
            "kind": SaleItemKind.FOOD.value,
            "label": raw.get("label") or item["name"],
            "qty": qty,
            "unit_price": item["unit_price"],
            "total_price": item["unit_price"] * qty,
            "duration_sec": None,
            "pc_class": None,
            "ref_id": item["id"],
            "price_snapshot": json.dumps(snapshot, ensure_ascii=True),
        }
