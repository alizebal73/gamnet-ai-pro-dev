import sqlite3

from gamenet.server.repositories.balance_repository import BalanceRepository
from gamenet.server.repositories.customer_repository import CustomerRepository
from gamenet.server.services.errors import InvalidState, NotFound


class BalanceService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._ledger = BalanceRepository(conn)
        self._customers = CustomerRepository(conn)

    def _require_customer(self, customer_id: str) -> dict:
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFound("Customer not found")
        return customer

    def balance_of(self, customer_id: str) -> int:
        self._require_customer(customer_id)
        return self._ledger.balance_of(customer_id)

    def ledger(self, customer_id: str, limit: int = 200) -> list[dict]:
        self._require_customer(customer_id)
        return self._ledger.list_for_customer(customer_id, limit=limit)

    def adjust(
        self,
        *,
        customer_id: str,
        amount: int,
        reason: str,
        created_by: str | None = None,
    ) -> dict:
        """Manual adjustment (Master Spec 86-87). Never lets balance go negative."""
        self._require_customer(customer_id)
        if amount == 0:
            raise ValueError("amount must be non-zero")
        if not (reason or "").strip():
            raise ValueError("reason is required")
        if self._ledger.balance_of(customer_id) + amount < 0:
            raise InvalidState("adjustment would make balance negative")
        return self._ledger.append(
            customer_id=customer_id, amount=amount, kind="ADJUSTMENT",
            reason=reason.strip(), created_by=created_by,
        )

    def recharge(
        self, *, customer_id: str, amount: int, sale_id: str,
        created_by: str | None = None,
    ) -> dict:
        self._require_customer(customer_id)
        if amount <= 0:
            raise ValueError("amount must be positive")
        return self._ledger.append(
            customer_id=customer_id, amount=amount, kind="RECHARGE",
            ref_type="sale", ref_id=sale_id, created_by=created_by,
        )

    def spend(
        self, *, customer_id: str, amount: int, payment_id: str,
        created_by: str | None = None,
    ) -> dict:
        self._require_customer(customer_id)
        if amount <= 0:
            raise ValueError("amount must be positive")
        if self._ledger.balance_of(customer_id) < amount:
            raise InvalidState(
                f"Insufficient balance ({self._ledger.balance_of(customer_id)} < {amount})"
            )
        return self._ledger.append(
            customer_id=customer_id, amount=-amount, kind="SPEND",
            ref_type="payment", ref_id=payment_id, created_by=created_by,
        )
