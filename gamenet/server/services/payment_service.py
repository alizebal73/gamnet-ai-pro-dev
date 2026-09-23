import json
import sqlite3
from typing import Any

from gamenet.server.config import settings
from gamenet.server.payments import (
    ProviderError,
    ProviderTimeout,
    get_provider,
)
from gamenet.server.repositories.payment_repository import PaymentRepository
from gamenet.server.repositories.sale_repository import SaleRepository
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.shared.enums import PaymentMethod, PaymentStatus, SaleStatus

# Server-side payment state machine (Master Spec 75/217).
TRANSITIONS: dict[str, set[str]] = {
    PaymentStatus.CREATED.value: {
        PaymentStatus.PENDING.value, PaymentStatus.PROCESSING.value,
        PaymentStatus.PAID.value, PaymentStatus.FAILED.value,
        PaymentStatus.UNKNOWN.value, PaymentStatus.CANCELLED.value,
    },
    PaymentStatus.PENDING.value: {
        PaymentStatus.PROCESSING.value, PaymentStatus.PAID.value,
        PaymentStatus.FAILED.value, PaymentStatus.UNKNOWN.value,
        PaymentStatus.CANCELLED.value,
    },
    PaymentStatus.PROCESSING.value: {
        PaymentStatus.PAID.value, PaymentStatus.FAILED.value,
        PaymentStatus.UNKNOWN.value, PaymentStatus.CANCELLED.value,
    },
    PaymentStatus.UNKNOWN.value: {
        PaymentStatus.PAID.value, PaymentStatus.FAILED.value,
        PaymentStatus.CANCELLED.value,
    },
    PaymentStatus.PAID.value: {PaymentStatus.REFUND_PENDING.value},
    PaymentStatus.FAILED.value: set(),
    PaymentStatus.CANCELLED.value: set(),
    PaymentStatus.REFUND_PENDING.value: {PaymentStatus.REFUNDED.value},
    PaymentStatus.REFUNDED.value: set(),
}

OPEN_STATUSES = [
    PaymentStatus.CREATED.value, PaymentStatus.PENDING.value,
    PaymentStatus.PROCESSING.value, PaymentStatus.UNKNOWN.value,
    PaymentStatus.PAID.value,
]


class PaymentService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._sales = SaleRepository(conn)
        self._payments = PaymentRepository(conn)

    def add_payment(
        self,
        *,
        sale_id: str,
        method: str,
        amount: int,
        provider_name: str | None = None,
        provider_ref: str | None = None,
        tendered: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict:
        sale = self._sales.get_sale(sale_id)
        if sale is None:
            raise NotFound("Sale not found")
        if sale["status"] != SaleStatus.DRAFT.value:
            raise InvalidState(f"Sale is {sale['status']}; payments are closed")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if method not in (
            PaymentMethod.CASH.value, PaymentMethod.CARD.value,
            PaymentMethod.BALANCE.value,
        ):
            raise ValueError(f"unknown method: {method}")

        applied = self._payments.sum_by_statuses(sale_id, OPEN_STATUSES)
        if applied + amount > sale["total"]:
            raise ValueError(
                f"amount exceeds outstanding balance ({sale['total'] - applied} left)"
            )

        if method == PaymentMethod.BALANCE.value:
            return self._balance_payment(
                sale=sale, amount=amount, meta=meta or {},
            )

        provider_name = provider_name or settings.payment_provider
        get_provider(provider_name)  # validates name early
        payment_id = next_number(self._conn, name="pay", prefix="PAY")
        meta_json = json.dumps(meta or {}, ensure_ascii=True)

        if method == PaymentMethod.CASH.value:
            if tendered is not None and tendered < amount:
                raise ValueError("tendered cash is less than amount")
            payment = self._payments.create(
                payment_id=payment_id, sale_id=sale_id, method=method,
                amount=amount, tendered=tendered,
                status=PaymentStatus.CREATED.value,
                provider="manual", meta=meta_json,
            )
            self._record_txn(payment, kind="CHARGE", status="PAID", message="cash received")
            self._transition(payment, PaymentStatus.PAID.value, reason="cash")
            return self._payments.get(payment_id)

        # CARD
        if provider_name == "manual":
            if not (provider_ref or "").strip():
                raise ValueError("provider_ref is required for manual card payments")
            payment = self._payments.create(
                payment_id=payment_id, sale_id=sale_id, method=method,
                amount=amount, status=PaymentStatus.PAID.value,
                provider="manual", provider_ref=provider_ref.strip(),
                meta=meta_json,
            )
            self._record_txn(
                payment, kind="CHARGE", status="PAID",
                provider_ref=provider_ref.strip(), message="manual card, ref recorded",
            )
            self._transition(payment, PaymentStatus.PAID.value, reason="manual card")
            return self._payments.get(payment_id)

        return self._automated_card_payment(
            payment_id=payment_id, sale_id=sale_id, amount=amount,
            provider_name=provider_name, meta=meta or {}, meta_json=meta_json,
        )

    def reconcile(self, payment_id: str) -> dict:
        payment = self._payments.get(payment_id)
        if payment is None:
            raise NotFound("Payment not found")
        if payment["status"] not in (
            PaymentStatus.PENDING.value, PaymentStatus.PROCESSING.value,
            PaymentStatus.UNKNOWN.value,
        ):
            raise InvalidState(
                f"Payment is {payment['status']}; nothing to reconcile"
            )
        if payment["provider"] == "manual":
            raise InvalidState("Manual payments cannot be reconciled")
        provider = get_provider(payment["provider"])
        meta = json.loads(payment["meta"]) if payment["meta"] else {}
        try:
            result = provider.check_status(
                provider_ref=payment["provider_ref"] or "", meta=meta
            )
        except ProviderTimeout:
            self._record_txn(payment, kind="INQUIRY", status="TIMEOUT",
                             message="inquiry timed out; still UNKNOWN")
            self._payments.add_event(
                payment_id=payment["id"], from_status=payment["status"],
                to_status=payment["status"], reason="inquiry timeout",
            )
            return self._payments.get(payment_id)
        if result.status == "PAID":
            self._record_txn(payment, kind="INQUIRY", status="PAID",
                             provider_ref=result.provider_ref, message=result.message)
            self._transition(payment, PaymentStatus.PAID.value,
                             reason="inquiry approved",
                             provider_ref=result.provider_ref or payment["provider_ref"])
        else:
            self._record_txn(payment, kind="INQUIRY", status="FAILED",
                             provider_ref=result.provider_ref, message=result.message)
            self._transition(payment, PaymentStatus.FAILED.value,
                             reason="inquiry declined")
        return self._payments.get(payment_id)

    def unknown_queue(self) -> list[dict]:
        return self._payments.unknown_queue()

    # ---- internals ----

    def _balance_payment(self, *, sale: dict, amount: int, meta: dict) -> dict:
        from gamenet.server.services.balance_service import BalanceService

        balance = BalanceService(self._conn)
        payment_id = next_number(self._conn, name="pay", prefix="PAY")
        payment = self._payments.create(
            payment_id=payment_id, sale_id=sale["id"],
            method=PaymentMethod.BALANCE.value, amount=amount,
            status=PaymentStatus.CREATED.value, provider="internal",
            meta=json.dumps(meta or {}, ensure_ascii=True),
        )
        # Raises InvalidState on insufficient balance; the route rolls back
        # the payment row with it (atomic).
        balance.spend(
            customer_id=sale["customer_id"], amount=amount,
            payment_id=payment_id,
        )
        self._record_txn(payment, kind="CHARGE", status="PAID",
                         message="balance debit")
        self._transition(payment, PaymentStatus.PAID.value, reason="balance")
        return self._payments.get(payment_id)

    def _automated_card_payment(
        self, *, payment_id: str, sale_id: str, amount: int,
        provider_name: str, meta: dict, meta_json: str,
    ) -> dict:
        provider = get_provider(provider_name)
        payment = self._payments.create(
            payment_id=payment_id, sale_id=sale_id,
            method=PaymentMethod.CARD.value, amount=amount,
            status=PaymentStatus.CREATED.value, provider=provider_name,
            meta=meta_json,
        )
        try:
            started = provider.start_payment(
                amount=amount, reference=payment_id, meta=meta
            )
        except ProviderTimeout as exc:
            self._record_txn(payment, kind="CHARGE", status="TIMEOUT", message=str(exc))
            self._transition(payment, PaymentStatus.UNKNOWN.value,
                             reason="no response at charge time")
            return self._payments.get(payment_id)
        except ProviderError as exc:
            self._record_txn(payment, kind="CHARGE", status="ERROR", message=str(exc))
            self._transition(payment, PaymentStatus.FAILED.value, reason=str(exc))
            return self._payments.get(payment_id)

        if started.status == "FAILED":
            self._record_txn(payment, kind="CHARGE", status="FAILED",
                             provider_ref=started.provider_ref, message=started.message)
            self._transition(payment, PaymentStatus.FAILED.value,
                             reason=started.message or "declined",
                             provider_ref=started.provider_ref)
            return self._payments.get(payment_id)

        self._record_txn(payment, kind="CHARGE", status="PROCESSING",
                         provider_ref=started.provider_ref, message=started.message)
        self._transition(payment, PaymentStatus.PROCESSING.value,
                         reason="charge accepted",
                         provider_ref=started.provider_ref)
        payment = self._payments.get(payment_id)

        # Immediate first inquiry so the normal path settles at once; the
        # UNKNOWN path above stays open for later reconciliation.
        try:
            checked = provider.check_status(
                provider_ref=payment["provider_ref"] or "", meta=meta
            )
        except ProviderTimeout:
            self._record_txn(payment, kind="INQUIRY", status="TIMEOUT",
                             message="first inquiry timed out")
            self._transition(payment, PaymentStatus.UNKNOWN.value,
                             reason="no response at inquiry time")
            return self._payments.get(payment_id)
        if checked.status == "PAID":
            self._record_txn(payment, kind="INQUIRY", status="PAID",
                             provider_ref=checked.provider_ref, message=checked.message)
            self._transition(payment, PaymentStatus.PAID.value,
                             reason="approved",
                             provider_ref=checked.provider_ref or payment["provider_ref"])
        else:
            self._record_txn(payment, kind="INQUIRY", status="FAILED",
                             provider_ref=checked.provider_ref, message=checked.message)
            self._transition(payment, PaymentStatus.FAILED.value,
                             reason=checked.message or "declined")
        return self._payments.get(payment_id)

    def _transition(
        self, payment: dict, to_status: str, *,
        reason: str | None = None, provider_ref: str | None = None,
    ) -> None:
        allowed = TRANSITIONS.get(payment["status"], set())
        if to_status != payment["status"] and to_status not in allowed:
            raise InvalidState(
                f"Cannot move payment from {payment['status']} to {to_status}"
            )
        self._payments.set_status(payment["id"], to_status, provider_ref=provider_ref)
        self._payments.add_event(
            payment_id=payment["id"], from_status=payment["status"],
            to_status=to_status, reason=reason,
        )

    def _record_txn(
        self, payment: dict, *, kind: str, status: str,
        provider_ref: str | None = None, message: str | None = None,
    ) -> None:
        self._payments.add_transaction(
            payment_id=payment["id"], kind=kind, status=status,
            amount=payment["amount"], provider_ref=provider_ref, message=message,
        )
