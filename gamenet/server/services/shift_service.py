"""Operator shifts + cash drawer reconciliation (P3-1).

Expected drawer = opening float + PAID cash on attached sales
                 + IN movements - OUT movements.
A shift with nonzero variance can only close with a written note, and
the variance stays on the record for the manager.
"""

import sqlite3

from gamenet.server.db import utc_now_iso
from gamenet.server.repositories.shift_repository import ShiftRepository
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.shared.enums import CashMovementKind, ShiftStatus


class ShiftService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._shifts = ShiftRepository(conn)

    def open(self, *, opened_by: str, opening_float: int = 0) -> dict:
        if opening_float < 0:
            raise ValueError("opening_float cannot be negative")
        if self._shifts.current_open() is not None:
            raise InvalidState("A shift is already open")
        shift_id = next_number(self._conn, name="shift", prefix="SHF")
        return self._shifts.create(shift_id, opened_by, opening_float,
                                   utc_now_iso())

    def current(self) -> dict:
        shift = self._shifts.current_open()
        if shift is None:
            raise NotFound("No open shift")
        return self._enrich(shift)

    def detail(self, shift_id: str) -> dict:
        shift = self._shifts.get(shift_id)
        if shift is None:
            raise NotFound("Shift not found")
        return self._enrich(shift)

    def history(self, limit: int = 50) -> list[dict]:
        return [self._enrich(s)
                for s in self._shifts.list_shifts(limit)]

    def close(self, *, closed_by: str, counted_cash: int,
              note: str | None = None) -> dict:
        if counted_cash < 0:
            raise ValueError("counted_cash cannot be negative")
        shift = self._shifts.current_open()
        if shift is None:
            raise NotFound("No open shift")
        expected = self.expected_cash(shift["id"],
                                      opening_float=shift["opening_float"])
        variance = counted_cash - expected
        if variance != 0 and not (note or "").strip():
            raise ValueError(
                "A note is required when the drawer does not balance")
        return self._shifts.close(
            shift["id"], closed_by=closed_by, closed_at=utc_now_iso(),
            expected=expected, counted=counted_cash, variance=variance,
            note=(note or "").strip() or None,
        )

    def add_movement(self, *, kind: str, amount: int, reason: str,
                     created_by: str) -> dict:
        try:
            ckind = CashMovementKind(kind)
        except ValueError:
            raise ValueError(f"Unknown movement kind: {kind}")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if not (reason or "").strip():
            raise ValueError("movement reason is required")
        shift = self._shifts.current_open()
        if shift is None:
            raise NotFound("No open shift")
        return self._shifts.add_movement(
            shift["id"], ckind.value, amount, reason.strip(),
            created_by, utc_now_iso(),
        )

    def expected_cash(self, shift_id: str, *,
                      opening_float: int | None = None) -> int:
        if opening_float is None:
            shift = self._shifts.get(shift_id)
            if shift is None:
                raise NotFound("Shift not found")
            opening_float = shift["opening_float"]
        return (
            opening_float
            + self._shifts.sum_cash_paid(shift_id)
            + self._shifts.sum_movements(shift_id, "IN")
            - self._shifts.sum_movements(shift_id, "OUT")
        )

    def _enrich(self, shift: dict) -> dict:
        shift = dict(shift)
        shift["cash_paid"] = self._shifts.sum_cash_paid(shift["id"])
        shift["moved_in"] = self._shifts.sum_movements(shift["id"], "IN")
        shift["moved_out"] = self._shifts.sum_movements(shift["id"], "OUT")
        if shift["status"] == ShiftStatus.OPEN.value:
            shift["expected_live"] = self.expected_cash(
                shift["id"], opening_float=shift["opening_float"])
        return shift
