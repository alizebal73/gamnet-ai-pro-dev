"""PC reservations with conflict detection (P3-4, Spec 51).

A BOOKED reservation blocks its (pc, time) window; seating converts it
into a real session (same transaction, so a failed seat keeps BOOKED).
Past-end BOOKED rows lazily become EXPIRED on any read/seat.
"""

import sqlite3
from datetime import datetime

from gamenet.server.db import to_utc_iso, utc_now_iso
from gamenet.server.repositories.customer_repository import CustomerRepository
from gamenet.server.repositories.pc_repository import PcRepository
from gamenet.server.repositories.reservation_repository import (
    ReservationRepository,
)
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.server.services.session_service import SessionService
from gamenet.shared.enums import ReservationStatus

PC_BLOCKED = {"RETIRED", "MAINTENANCE", "ERROR"}


def _normalize(when: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat((when or "").replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be ISO-8601")
    if dt.tzinfo is None:
        raise ValueError(f"{field} must carry a timezone")
    return dt


class ReservationService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._reservations = ReservationRepository(conn)
        self._customers = CustomerRepository(conn)
        self._pcs = PcRepository(conn)

    def book(self, *, customer_id: str, pc_id: str, starts_at: str,
             ends_at: str, note: str | None,
             created_by: str) -> dict:
        start = _normalize(starts_at, "starts_at")
        end = _normalize(ends_at, "ends_at")
        if end <= start:
            raise ValueError("ends_at must be after starts_at")
        now = datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00"))
        if end <= now:
            raise ValueError("reservation ends in the past")
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFound("Customer not found")
        if customer["status"] != "ACTIVE":
            raise InvalidState("Customer is not active")
        pc = self._pcs.get(pc_id)
        if pc is None:
            raise NotFound("PC not found")
        if pc["status"] in PC_BLOCKED:
            raise InvalidState(f"PC {pc['device_code']} is {pc['status']}")
        start_s, end_s = to_utc_iso(start), to_utc_iso(end)
        clashes = self._reservations.overlapping(pc_id, start_s, end_s)
        if clashes:
            raise InvalidState(
                f"PC {pc['device_code']} already reserved "
                f"({clashes[0]['id']}) in that window")
        res_id = next_number(self._conn, name="reservation", prefix="RES")
        return self._reservations.create(
            res_id, customer_id=customer_id, pc_id=pc_id,
            starts_at=start_s, ends_at=end_s, note=(note or "").strip()
            or None, created_by=created_by, now=utc_now_iso(),
        )

    def cancel(self, res_id: str, *, reason: str,
               actor_user_id: str | None = None) -> dict:
        res = self._require(res_id)
        if res["status"] != ReservationStatus.BOOKED.value:
            raise InvalidState(
                f"Reservation is {res['status']}, cannot cancel")
        if not (reason or "").strip():
            raise ValueError("cancel reason is required")
        return self._reservations.set_status(
            res_id, ReservationStatus.CANCELLED.value, utc_now_iso(),
            cancel_reason=reason.strip(),
        )

    def no_show(self, res_id: str) -> dict:
        res = self._require(res_id)
        if res["status"] != ReservationStatus.BOOKED.value:
            raise InvalidState(
                f"Reservation is {res['status']}, cannot mark no-show")
        return self._reservations.set_status(
            res_id, ReservationStatus.NO_SHOW.value, utc_now_iso())

    def seat(self, res_id: str, *,
             actor_user_id: str | None = None) -> dict:
        self._refresh()
        res = self._require(res_id)
        if res["status"] != ReservationStatus.BOOKED.value:
            raise InvalidState(
                f"Reservation is {res['status']}, cannot seat")
        sessions = SessionService(self._conn)
        created = sessions.create(
            customer_id=res["customer_id"], pc_id=res["pc_id"],
            created_by=actor_user_id,
        )
        session = sessions.authorize(
            created["id"], actor_user_id=actor_user_id)
        updated = self._reservations.set_status(
            res_id, ReservationStatus.SEATED.value, utc_now_iso())
        return {"reservation": updated, "session": session}

    def get(self, res_id: str) -> dict:
        self._refresh()
        return self._require(res_id)

    def list(self, **filters) -> list[dict]:
        self._refresh()
        return self._reservations.list_reservations(**filters)

    def _require(self, res_id: str) -> dict:
        res = self._reservations.get(res_id)
        if res is None:
            raise NotFound("Reservation not found")
        return res

    def _refresh(self) -> None:
        self._reservations.expire_past(utc_now_iso())
