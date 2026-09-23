"""Customer waiting queue (P3-4, Spec 52).

FIFO by default; higher `priority` first; VIPs jump the queue only when
the `queue_vip_priority` setting is enabled. Stale entries lazily expire
after `queue_expire_min` minutes.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from gamenet.server.db import to_utc_iso, utc_now_iso
from gamenet.server.repositories.customer_repository import CustomerRepository
from gamenet.server.repositories.pc_repository import PcRepository
from gamenet.server.repositories.queue_repository import QueueRepository
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.credit_service import CreditService
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.server.services.session_service import SessionService
from gamenet.shared.enums import QueueEntryStatus


class QueueService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._queue = QueueRepository(conn)
        self._customers = CustomerRepository(conn)
        self._pcs = PcRepository(conn)
        self._settings = SettingsRepository(conn)
        self._credit = CreditService(conn)

    def join(self, *, customer_id: str, pc_id: str | None = None,
             priority: int = 0, note: str | None = None,
             created_by: str) -> dict:
        self._refresh()
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFound("Customer not found")
        if customer["status"] != "ACTIVE":
            raise InvalidState("Customer is not active")
        if pc_id is not None and self._pcs.get(pc_id) is None:
            raise NotFound("PC not found")
        if not 0 <= priority <= 100:
            raise ValueError("priority must be 0..100")
        if self._queue.waiting_for_customer(customer_id) is not None:
            raise InvalidState("Customer is already in the queue")
        entry_id = next_number(self._conn, name="queue", prefix="QUE")
        entry = self._queue.create(
            entry_id, customer_id=customer_id, pc_id=pc_id,
            priority=priority, note=(note or "").strip() or None,
            created_by=created_by, now=utc_now_iso(),
        )
        return self._enrich(entry, boosted=False, position=None)

    def call(self, entry_id: str) -> dict:
        self._refresh()
        entry = self._require(entry_id)
        if entry["status"] != QueueEntryStatus.WAITING.value:
            raise InvalidState(
                f"Entry is {entry['status']}, cannot call")
        updated = self._queue.set_status(
            entry_id, QueueEntryStatus.CALLED.value, utc_now_iso(),
            called=True,
        )
        return self._enrich(updated, boosted=False, position=None)

    def seat(self, entry_id: str, *, pc_id: str | None = None,
             actor_user_id: str | None = None) -> dict:
        self._refresh()
        entry = self._require(entry_id)
        if entry["status"] not in (QueueEntryStatus.WAITING.value,
                                   QueueEntryStatus.CALLED.value):
            raise InvalidState(
                f"Entry is {entry['status']}, cannot seat")
        target_pc = pc_id or entry["pc_id"]
        if target_pc is None:
            raise InvalidState("A PC must be chosen to seat this entry")
        sessions = SessionService(self._conn)
        created = sessions.create(
            customer_id=entry["customer_id"], pc_id=target_pc,
            created_by=actor_user_id,
        )
        session = sessions.authorize(
            created["id"], actor_user_id=actor_user_id)
        updated = self._queue.set_status(
            entry_id, QueueEntryStatus.SEATED.value, utc_now_iso())
        return {"entry": self._enrich(updated, boosted=False,
                                      position=None),
                "session": session}

    def cancel(self, entry_id: str) -> dict:
        entry = self._require(entry_id)
        if entry["status"] not in (QueueEntryStatus.WAITING.value,
                                   QueueEntryStatus.CALLED.value):
            raise InvalidState(
                f"Entry is {entry['status']}, cannot cancel")
        updated = self._queue.set_status(
            entry_id, QueueEntryStatus.CANCELLED.value, utc_now_iso())
        return self._enrich(updated, boosted=False, position=None)

    def list(self) -> list[dict]:
        self._refresh()
        vip_boost = self._settings.get("queue_vip_priority", "0") == "1"
        enriched = []
        for entry in self._queue.list_active():
            boosted = bool(
                vip_boost
                and self._credit.active_vip(entry["customer_id"])
                is not None
            )
            enriched.append((entry, boosted))
        enriched.sort(key=lambda pair: (
            not pair[1], -pair[0]["priority"], pair[0]["created_at"],
        ))
        return [self._enrich(entry, boosted=boosted, position=index + 1)
                for index, (entry, boosted) in enumerate(enriched)]

    def _require(self, entry_id: str) -> dict:
        entry = self._queue.get(entry_id)
        if entry is None:
            raise NotFound("Queue entry not found")
        return entry

    def _enrich(self, entry: dict, *, boosted: bool,
                position: int | None) -> dict:
        entry = dict(entry)
        customer = self._customers.get_by_id(entry["customer_id"])
        entry["customer_name"] = customer["name"] if customer else None
        entry["vip_boosted"] = boosted
        entry["position"] = position
        return entry

    def _refresh(self) -> None:
        minutes = self._settings.get_int("queue_expire_min", 60)
        cutoff = to_utc_iso(datetime.now(timezone.utc)
                            - timedelta(minutes=minutes))
        self._queue.expire_older_than(cutoff, utc_now_iso())
