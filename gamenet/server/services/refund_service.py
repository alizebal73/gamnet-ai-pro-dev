"""Refunds: money out + proportional credit clawback (P3-2).

Rules:
  - Only CONFIRMED sales; total refunds can never exceed the sale total.
  - CASH refunds need an open shift (an OUT drawer movement is recorded
    automatically); BALANCE refunds credit the customer back directly.
  - TIME/PACKAGE credit granted by the sale is revoked CUMULATIVELY:
    after each refund, total revoked = fraction-of-original-grant, so a
    sequence of partial refunds sums exactly. Only the *remaining* part
    is revoked; already consumed seconds are never clawed back.
  - RECHARGE money is clawed from the balance the same cumulative way,
    but only if the customer has not spent it (else 409: strict, no
    negative balance).
  - VIPs granted by the sale are cancelled when the sale becomes *fully*
    refunded; the normal PENDING chain promotion still applies.
"""

import sqlite3

from gamenet.server.db import utc_now_iso
from gamenet.server.repositories.balance_repository import BalanceRepository
from gamenet.server.repositories.entitlement_repository import (
    EntitlementRepository,
)
from gamenet.server.repositories.refund_repository import RefundRepository
from gamenet.server.repositories.sale_repository import SaleRepository
from gamenet.server.repositories.shift_repository import ShiftRepository
from gamenet.server.services.credit_service import CreditService
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.shared.enums import (
    EntitlementKind,
    EntitlementStatus,
    SaleStatus,
)

TIME_KINDS = {
    EntitlementKind.TIME_CREDIT.value,
    EntitlementKind.PACKAGE_CREDIT.value,
}
REFUND_METHODS = ("CASH", "BALANCE")


class RefundService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._sales = SaleRepository(conn)
        self._refunds = RefundRepository(conn)
        self._ents = EntitlementRepository(conn)
        self._balance = BalanceRepository(conn)
        self._shifts = ShiftRepository(conn)
        self._credit = CreditService(conn)

    def refund(self, *, sale_id: str, amount: int, method: str,
               reason: str, created_by: str) -> dict:
        sale = self._sales.get_sale(sale_id)
        if sale is None:
            raise NotFound("Sale not found")
        if sale["status"] == SaleStatus.DRAFT.value:
            raise InvalidState(
                "Sale is still a draft; cancel it instead of refunding")
        if sale["status"] != SaleStatus.CONFIRMED.value:
            raise InvalidState(
                f"Sale is {sale['status']}, cannot refund")
        method = (method or "").upper()
        if method not in REFUND_METHODS:
            raise ValueError(f"Unknown refund method: {method}")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if not (reason or "").strip():
            raise ValueError("refund reason is required")
        already = self._refunds.sum_for_sale(sale_id)
        if amount > sale["total"] - already:
            raise InvalidState("Refund exceeds the refundable amount")
        cum_fraction = (already + amount) / sale["total"]

        # Pre-checks before any write.
        shift_id = None
        if method == "CASH":
            shift = self._shifts.current_open()
            if shift is None:
                raise InvalidState("CASH refund needs an open shift")
            shift_id = shift["id"]
        recharged = self._recharged_by_sale(sale_id)
        claw = 0
        if recharged > 0:
            claw_target = int(recharged * cum_fraction)
            claw = max(0, claw_target - self._clawed_by_sale(sale_id))
        if claw > 0 and self._balance.balance_of(sale["customer_id"]) < claw:
            raise InvalidState(
                "Customer has spent the recharged balance; "
                "refund a smaller amount")

        now = utc_now_iso()
        reason = reason.strip()
        if method == "CASH":
            self._shifts.add_movement(
                shift_id, "OUT", amount, f"Refund {sale_id}: {reason}",
                created_by, now,
            )
        else:
            self._balance.append(
                customer_id=sale["customer_id"], amount=amount,
                kind="REFUND", ref_type="sale", ref_id=sale_id,
                reason=reason, created_by=created_by,
            )

        revoked_sec = 0
        for ent in self._ents.list_for_sale(sale_id):
            if ent["kind"] in TIME_KINDS and ent["status"] == (
                    EntitlementStatus.ACTIVE.value):
                revoked_so_far = self._revoked_for_entitlement(ent["id"])
                original = (ent["granted_sec"] or 0) + revoked_so_far
                target = int(original * cum_fraction)
                remaining = (ent["granted_sec"] or 0) - (
                    ent["consumed_sec"] or 0)
                revoke = max(0, min(remaining,
                                    target - revoked_so_far))
                if revoke > 0:
                    self._ents.revoke_grant(ent["id"], revoke)
                    self._ents.append_ledger(
                        entitlement_id=ent["id"], delta_sec=-revoke,
                        kind="REVOKE", ref_type="sale", ref_id=sale_id,
                        reason=f"Refund {sale_id}: {reason}",
                        created_by=created_by,
                    )
                    revoked_sec += revoke
                if remaining - revoke <= 0:
                    self._ents.set_status(
                        ent["id"], EntitlementStatus.CANCELLED.value)
        if claw > 0:
            self._balance.append(
                customer_id=sale["customer_id"], amount=-claw,
                kind="CLAWBACK", ref_type="sale", ref_id=sale_id,
                reason=f"Refund {sale_id}: {reason}",
                created_by=created_by,
            )

        refund_id = next_number(self._conn, name="refund", prefix="RFD")
        refund = self._refunds.create(
            refund_id, sale_id, amount, method, reason, created_by,
            shift_id, now,
        )

        vips_cancelled: list[str] = []
        if already + amount >= sale["total"]:
            for ent in self._ents.list_for_sale(sale_id):
                if ent["kind"] == EntitlementKind.VIP.value and ent[
                        "status"] in (
                        EntitlementStatus.ACTIVE.value,
                        EntitlementStatus.PENDING.value):
                    self._ents.set_status(
                        ent["id"], EntitlementStatus.CANCELLED.value)
                    vips_cancelled.append(ent["id"])
            if vips_cancelled:
                self._credit.refresh_vip_states(sale["customer_id"])

        return {
            "refund": refund,
            "revoked_sec": revoked_sec,
            "clawed_balance": claw,
            "vips_cancelled": vips_cancelled,
            "refunded_total": already + amount,
        }

    def list_for_sale(self, sale_id: str) -> list[dict]:
        if self._sales.get_sale(sale_id) is None:
            raise NotFound("Sale not found")
        return self._refunds.list_for_sale(sale_id)

    def total_for_sale(self, sale_id: str) -> int:
        return self._refunds.sum_for_sale(sale_id)

    def _recharged_by_sale(self, sale_id: str) -> int:
        row = self._conn.execute(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM customer_balance_ledger
               WHERE kind = 'RECHARGE' AND ref_type = 'sale'
                 AND ref_id = ?""",
            (sale_id,),
        ).fetchone()
        return row["total"]

    def _clawed_by_sale(self, sale_id: str) -> int:
        row = self._conn.execute(
            """SELECT COALESCE(SUM(-amount), 0) AS total
               FROM customer_balance_ledger
               WHERE kind = 'CLAWBACK' AND ref_type = 'sale'
                 AND ref_id = ?""",
            (sale_id,),
        ).fetchone()
        return row["total"]

    def _revoked_for_entitlement(self, entitlement_id: str) -> int:
        row = self._conn.execute(
            """SELECT COALESCE(SUM(-delta_sec), 0) AS total
               FROM entitlement_ledger
               WHERE entitlement_id = ? AND kind = 'REVOKE'""",
            (entitlement_id,),
        ).fetchone()
        return row["total"]
