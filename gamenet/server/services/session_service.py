"""Gaming sessions (Master Spec 25-31, 41-46, 157-166, 216).

Lifecycle: CREATED -> AUTHORIZED -> ACTIVE -> PAUSED -> ACTIVE ... -> ENDED.
INTERRUPTED / CONNECTION_LOST are set by the heartbeat layer (P2).

Time accounting uses SERVER timestamps only (Spec 47): every pause/end/
transfer commits elapsed seconds from the credit ledger. Timers never run
on client clocks.
"""

import sqlite3
from datetime import datetime

from gamenet.server.db import utc_now_iso
from gamenet.server.repositories.customer_repository import CustomerRepository
from gamenet.server.repositories.pc_repository import PcRepository
from gamenet.server.repositories.session_repository import SessionRepository
from gamenet.server.services.credit_service import CreditService
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.shared.enums import SessionStatus

ACTIVE_STATUSES = [
    SessionStatus.AUTHORIZED.value, SessionStatus.ACTIVE.value,
    SessionStatus.PAUSED.value, SessionStatus.INTERRUPTED.value,
    SessionStatus.CONNECTION_LOST.value,
]

PC_BLOCKED_STATUSES = {"RETIRED", "MAINTENANCE", "ERROR"}


class SessionService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._sessions = SessionRepository(conn)
        self._customers = CustomerRepository(conn)
        self._pcs = PcRepository(conn)
        self._credit = CreditService(conn)

    # ---- reads ----

    def detail(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFound("Session not found")
        session["events"] = self._sessions.list_events(session_id)
        session["consumptions"] = self._sessions.list_consumptions(session_id)
        session["customer_remaining_sec"] = self._credit.remaining_sec(
            session["customer_id"]
        )
        return session

    # ---- lifecycle ----

    def create(
        self,
        *,
        customer_id: str,
        pc_id: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        customer = self._customers.get_by_id(customer_id)
        if customer is None:
            raise NotFound("Customer not found")
        if customer["status"] != "ACTIVE":
            raise InvalidState("Customer is not active")
        existing = self._sessions.active_for_customer(customer_id)
        if existing is not None:
            raise InvalidState(
                f"Customer already has an active session {existing['id']} "
                f"on PC {existing['pc_id']} ({existing['status']})"
            )
        if self._credit.remaining_sec(customer_id) <= 0:
            raise InvalidState("Customer has no gaming credit")
        if pc_id is not None:
            self._require_usable_pc(pc_id)
        session_id = next_number(self._conn, name="ses", prefix="SES")
        session = self._sessions.create(
            session_id=session_id, customer_id=customer_id, pc_id=pc_id,
            created_by=created_by,
        )
        self._sessions.add_event(
            session_id=session_id, kind="CREATED", to_status=session["status"],
            pc_id=pc_id, actor_user_id=created_by,
        )
        return self.detail(session_id)

    def authorize(
        self,
        session_id: str,
        *,
        pc_id: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        session = self._require(session_id)
        if session["status"] != SessionStatus.CREATED.value:
            raise InvalidState(f"Session is {session['status']}, cannot authorize")
        target_pc = pc_id or session["pc_id"]
        if target_pc is None:
            raise InvalidState("A PC must be assigned before authorization")
        self._require_usable_pc(target_pc)
        if self._credit.remaining_sec(session["customer_id"]) <= 0:
            raise InvalidState("Customer has no gaming credit")
        self._sessions.update(session_id, {
            "pc_id": target_pc, "status": SessionStatus.AUTHORIZED.value,
        })
        self._sessions.add_event(
            session_id=session_id, kind="AUTHORIZED",
            from_status=session["status"],
            to_status=SessionStatus.AUTHORIZED.value, pc_id=target_pc,
            actor_user_id=actor_user_id,
        )
        return self.detail(session_id)

    def start(self, session_id: str, *, actor_user_id: str | None = None) -> dict:
        session = self._require(session_id)
        if session["status"] != SessionStatus.AUTHORIZED.value:
            raise InvalidState(f"Session is {session['status']}, cannot start")
        if not session["pc_id"]:
            raise InvalidState("No PC assigned to this session")
        self._require_usable_pc(session["pc_id"], ignore_session=session_id)
        if self._credit.remaining_sec(session["customer_id"]) <= 0:
            raise InvalidState("Customer has no gaming credit")
        now = utc_now_iso()
        self._sessions.update(session_id, {
            "status": SessionStatus.ACTIVE.value,
            "started_at": session["started_at"] or now,
            "last_accounted_at": now,
        })
        self._sessions.add_event(
            session_id=session_id, kind="STARTED", from_status=session["status"],
            to_status=SessionStatus.ACTIVE.value, pc_id=session["pc_id"],
            actor_user_id=actor_user_id,
        )
        return self.detail(session_id)

    def pause(
        self,
        session_id: str,
        *,
        reason: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        session = self._require(session_id)
        if session["status"] != SessionStatus.ACTIVE.value:
            raise InvalidState(f"Session is {session['status']}, cannot pause")
        now = utc_now_iso()
        elapsed = self._elapsed_sec(session, now)
        if elapsed > 0:
            consumed = self._commit_consumption(session, elapsed, now, kind="TICK")
            if consumed < elapsed:
                # Credit ran out mid-session: end it, nothing is lost or owed.
                return self._finish(
                    session, now, reason="CREDIT_EXHAUSTED",
                    actor_user_id=actor_user_id,
                )
        else:
            self._sessions.update(session_id, {"last_accounted_at": now})
        self._sessions.update(session_id, {"status": SessionStatus.PAUSED.value})
        self._sessions.add_event(
            session_id=session_id, kind="PAUSED", from_status=session["status"],
            to_status=SessionStatus.PAUSED.value, pc_id=session["pc_id"],
            actor_user_id=actor_user_id, reason=reason,
        )
        return self.detail(session_id)

    def resume(self, session_id: str, *, actor_user_id: str | None = None) -> dict:
        session = self._require(session_id)
        if session["status"] != SessionStatus.PAUSED.value:
            raise InvalidState(f"Session is {session['status']}, cannot resume")
        if not session["pc_id"]:
            raise InvalidState("No PC assigned to this session")
        self._require_usable_pc(session["pc_id"], ignore_session=session_id)
        if self._credit.remaining_sec(session["customer_id"]) <= 0:
            raise InvalidState("Customer has no gaming credit")
        now = utc_now_iso()
        self._sessions.update(session_id, {
            "status": SessionStatus.ACTIVE.value, "last_accounted_at": now,
        })
        self._sessions.add_event(
            session_id=session_id, kind="RESUMED", from_status=session["status"],
            to_status=SessionStatus.ACTIVE.value, pc_id=session["pc_id"],
            actor_user_id=actor_user_id,
        )
        return self.detail(session_id)

    def end(
        self,
        session_id: str,
        *,
        reason: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        session = self._require(session_id)
        if session["status"] not in (
            SessionStatus.AUTHORIZED.value, SessionStatus.ACTIVE.value,
            SessionStatus.PAUSED.value, SessionStatus.INTERRUPTED.value,
            SessionStatus.CONNECTION_LOST.value,
        ):
            raise InvalidState(f"Session is {session['status']}, cannot end")
        now = utc_now_iso()
        if session["status"] == SessionStatus.ACTIVE.value:
            elapsed = self._elapsed_sec(session, now)
            if elapsed > 0:
                self._commit_consumption(session, elapsed, now, kind="FINALIZE")
        return self._finish(session, now, reason=reason or "ENDED",
                            actor_user_id=actor_user_id)

    def cancel(
        self,
        session_id: str,
        *,
        reason: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        session = self._require(session_id)
        if session["status"] not in (
            SessionStatus.CREATED.value, SessionStatus.AUTHORIZED.value,
        ):
            raise InvalidState(f"Session is {session['status']}, cannot cancel")
        self._sessions.update(session_id, {
            "status": SessionStatus.CANCELLED.value, "ended_at": utc_now_iso(),
            "ended_reason": reason or "CANCELLED",
        })
        self._sessions.add_event(
            session_id=session_id, kind="CANCELLED", from_status=session["status"],
            to_status=SessionStatus.CANCELLED.value, pc_id=session["pc_id"],
            actor_user_id=actor_user_id, reason=reason,
        )
        return self.detail(session_id)

    def transfer(
        self,
        session_id: str,
        *,
        new_pc_id: str,
        reason: str,
        actor_user_id: str | None = None,
    ) -> dict:
        session = self._require(session_id)
        if session["status"] not in (
            SessionStatus.AUTHORIZED.value, SessionStatus.ACTIVE.value,
            SessionStatus.PAUSED.value,
        ):
            raise InvalidState(
                f"Session is {session['status']}, cannot transfer"
            )
        if not (reason or "").strip():
            raise ValueError("transfer reason is required")
        if new_pc_id == session["pc_id"]:
            raise ValueError("new PC is the same as current PC")
        self._require_usable_pc(new_pc_id)
        now = utc_now_iso()
        if session["status"] == SessionStatus.ACTIVE.value:
            elapsed = self._elapsed_sec(session, now)
            if elapsed > 0:
                self._commit_consumption(session, elapsed, now, kind="TICK")
            else:
                self._sessions.update(session_id, {"last_accounted_at": now})
        old_pc = session["pc_id"]
        self._sessions.update(session_id, {"pc_id": new_pc_id})
        self._sessions.add_event(
            session_id=session_id, kind="TRANSFERRED",
            from_status=session["status"], to_status=session["status"],
            pc_id=new_pc_id, actor_user_id=actor_user_id,
            reason=f"{old_pc} -> {new_pc_id}: {reason.strip()}",
        )
        return self.detail(session_id)

    # ---- internals ----

    def _require(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFound("Session not found")
        return session

    def _require_usable_pc(
        self, pc_id: str, *, ignore_session: str | None = None
    ) -> dict:
        pc = self._pcs.get(pc_id)
        if pc is None:
            raise NotFound("PC not found")
        if pc["status"] in PC_BLOCKED_STATUSES:
            raise InvalidState(f"PC {pc['device_code']} is {pc['status']}")
        busy = self._sessions.active_for_pc(pc_id)
        if busy is not None and busy["id"] != ignore_session:
            raise InvalidState(
                f"PC {pc['device_code']} is busy "
                f"(session {busy['id']}, {busy['status']})"
            )
        return pc

    @staticmethod
    def _elapsed_sec(session: dict, now_iso: str) -> int:
        anchor = session["last_accounted_at"] or session["started_at"]
        if not anchor:
            return 0
        start = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return max(0, int((now - start).total_seconds()))

    def _commit_consumption(
        self, session: dict, elapsed: int, now_iso: str, *, kind: str,
    ) -> int:
        """Consume elapsed seconds from credit. Returns seconds consumed."""
        available = self._credit.remaining_sec(session["customer_id"])
        take = min(elapsed, available)
        anchor = session["last_accounted_at"] or session["started_at"]
        if take > 0:
            breakdown = self._credit.consume(
                customer_id=session["customer_id"], seconds=take,
                ref_type="session", ref_id=session["id"],
            )
            for part in breakdown:
                self._sessions.add_consumption(
                    session_id=session["id"],
                    entitlement_id=part["entitlement_id"], seconds=part["consumed_sec"],
                    period_start=anchor, period_end=now_iso, kind=kind,
                )
        self._sessions.update(session["id"], {
            "last_accounted_at": now_iso,
            "total_consumed_sec": session["total_consumed_sec"] + take,
        })
        return take

    def _finish(
        self, session: dict, now_iso: str, *, reason: str,
        actor_user_id: str | None,
    ) -> dict:
        self._sessions.update(session["id"], {
            "status": SessionStatus.ENDED.value, "ended_at": now_iso,
            "ended_reason": reason,
        })
        self._sessions.add_event(
            session_id=session["id"], kind="ENDED", from_status=session["status"],
            to_status=SessionStatus.ENDED.value, pc_id=session["pc_id"],
            actor_user_id=actor_user_id, reason=reason,
        )
        return self.detail(session["id"])
