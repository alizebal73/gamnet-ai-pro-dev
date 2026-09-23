"""One-tap operator flows (P3-5): quick customer + quick sale.

Both run in the caller's transaction: any failure rolls back everything,
so a quick sale never leaves a half-paid draft behind.
"""

import sqlite3

from gamenet.server.models.schemas import CustomerCreate
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.customer_service import CustomerService
from gamenet.server.services.payment_service import PaymentService
from gamenet.server.services.sale_service import SaleService


class QuickService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def quick_customer(self, *, name: str, pin: str,
                       mobile: str | None = None,
                       gaming_name: str | None = None,
                       recharge_amount: int | None = None,
                       auth: AuthContext) -> dict:
        customer = CustomerService(self._conn).create_customer(
            CustomerCreate(name=name, pin=pin, mobile=mobile,
                           gaming_name=gaming_name)
        )
        customer_id = customer.id
        sale = None
        if recharge_amount:
            sale = self.quick_sale(
                customer_id=customer_id,
                items=[{"kind": "RECHARGE",
                        "unit_price": recharge_amount}],
                payments=[{"method": "CASH",
                           "amount": recharge_amount}],
                auth=auth,
            )
        return {"customer": customer.model_dump(mode="json"),
                "sale": sale}

    def quick_sale(self, *, customer_id: str, items: list[dict],
                   payments: list[dict], discount_pct: int = 0,
                   discount_reason: str | None = None,
                   auth: AuthContext) -> dict:
        sales = SaleService(self._conn)
        pays = PaymentService(self._conn)
        draft = sales.create_draft(
            customer_id=customer_id, items=items,
            discount_pct=discount_pct, discount_reason=discount_reason,
            auth=auth,
        )
        for pay in payments:
            pays.add_payment(
                sale_id=draft["id"], method=pay["method"],
                amount=pay["amount"],
                provider_name=pay.get("provider"),
                provider_ref=pay.get("provider_ref"),
                tendered=pay.get("tendered"), meta=pay.get("meta"),
            )
        return sales.confirm(draft["id"], created_by=auth.user_id)
