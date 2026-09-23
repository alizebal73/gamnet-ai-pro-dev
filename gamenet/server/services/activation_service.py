"""Payment First -> Activation Second (Master Spec 76).

Called atomically inside sale confirmation: every confirmed sale item
grants its entitlement (credit / VIP / balance). Nothing is granted for
draft or cancelled sales.
"""

import sqlite3

from gamenet.server.repositories.catalog_repository import CatalogRepository
from gamenet.server.services.balance_service import BalanceService
from gamenet.server.services.credit_service import CreditService
from gamenet.server.services.errors import InvalidState
from gamenet.shared.enums import EntitlementKind, SaleItemKind


def grant_for_sale(
    conn: sqlite3.Connection, sale: dict, items: list[dict],
    *, created_by: str | None = None,
) -> list[dict]:
    credit = CreditService(conn)
    balance = BalanceService(conn)
    catalog = CatalogRepository(conn)
    granted = []
    for item in items:
        kind = item["kind"]
        if kind == SaleItemKind.TIME.value:
            granted.append(credit.grant_time_credit(
                customer_id=sale["customer_id"], seconds=item["duration_sec"],
                sale_id=sale["id"], sale_item_id=item["id"],
                created_by=created_by,
            ))
        elif kind == SaleItemKind.RECHARGE.value:
            granted.append(balance.recharge(
                customer_id=sale["customer_id"], amount=item["total_price"],
                sale_id=sale["id"], created_by=created_by,
            ))
        elif kind == SaleItemKind.PACKAGE.value:
            pkg = catalog.get_package(item["ref_id"])
            if pkg is None:
                raise InvalidState(f"package {item['ref_id']} no longer exists")
            granted.append(credit.grant_time_credit(
                customer_id=sale["customer_id"],
                seconds=pkg["duration_sec"] + (pkg["bonus_sec"] or 0),
                sale_id=sale["id"], sale_item_id=item["id"],
                validity_days=pkg["validity_days"],
                kind=EntitlementKind.PACKAGE_CREDIT.value,
                ref_id=pkg["id"], created_by=created_by,
            ))
        elif kind == SaleItemKind.VIP.value:
            plan = catalog.get_vip_plan(item["ref_id"])
            if plan is None:
                raise InvalidState(f"VIP plan {item['ref_id']} no longer exists")
            granted.append(credit.grant_vip(
                customer_id=sale["customer_id"],
                duration_days=plan["duration_days"],
                discount_pct=plan["discount_pct"] or 0,
                sale_id=sale["id"], sale_item_id=item["id"],
                ref_id=plan["id"],
            ))
        else:
            raise InvalidState(f"cannot activate item kind '{kind}'")
    return granted
