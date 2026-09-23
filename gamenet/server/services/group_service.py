"""Group sessions: several customers, one shared end (P3-4, Spec 53).

Each member keeps its own sale/payment/customer; the group only links
their sessions so the operator can end them together at a shared time.
"""

import sqlite3
from datetime import datetime

from gamenet.server.db import utc_now_iso
from gamenet.server.repositories.group_repository import GroupRepository
from gamenet.server.repositories.session_repository import SessionRepository
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.numbering import next_number
from gamenet.server.services.session_service import SessionService
from gamenet.shared.enums import SessionGroupStatus, SessionStatus

TERMINAL = {SessionStatus.ENDED.value, SessionStatus.CANCELLED.value}
JOINABLE = {SessionStatus.AUTHORIZED.value, SessionStatus.ACTIVE.value,
            SessionStatus.PAUSED.value}


class GroupService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._groups = GroupRepository(conn)
        self._sessions = SessionRepository(conn)

    def create(self, *, name: str | None = None,
               shared_ends_at: str | None = None,
               created_by: str) -> dict:
        if shared_ends_at is not None:
            try:
                ends = datetime.fromisoformat(
                    shared_ends_at.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("shared_ends_at must be ISO-8601")
            now = datetime.fromisoformat(
                utc_now_iso().replace("Z", "+00:00"))
            if ends <= now:
                raise ValueError("shared_ends_at must be in the future")
        group_id = next_number(self._conn, name="sessgroup", prefix="GRP")
        group = self._groups.create_group(
            group_id, name=(name or "").strip() or None,
            shared_ends_at=shared_ends_at, created_by=created_by,
            now=utc_now_iso(),
        )
        return self._enrich(group)

    def add_member(self, group_id: str, session_id: str) -> dict:
        group = self._require_open(group_id)
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFound("Session not found")
        if session["status"] not in JOINABLE:
            raise InvalidState(
                f"Session is {session['status']}, cannot join a group")
        if session.get("group_id") is not None:
            raise InvalidState("Session is already in a group")
        self._groups.add_member(session_id, group_id)
        return self._enrich(group)

    def remove_member(self, group_id: str, session_id: str) -> dict:
        group = self._require_open(group_id)
        session = self._sessions.get(session_id)
        if session is None or session.get("group_id") != group_id:
            raise NotFound("Session is not a member of this group")
        self._groups.remove_member(session_id)
        return self._enrich(group)

    def end_all(self, group_id: str, *, reason: str | None = None,
                actor_user_id: str | None = None) -> dict:
        group = self._require_open(group_id)
        sessions = SessionService(self._conn)
        ended, skipped = [], []
        for member in self._groups.members(group_id):
            if member["status"] in TERMINAL:
                skipped.append({"session_id": member["id"],
                                "reason": member["status"]})
                continue
            try:
                sessions.end(member["id"],
                             reason=reason or "GROUP_END",
                             actor_user_id=actor_user_id)
                ended.append(member["id"])
            except (InvalidState, NotFound, ValueError) as exc:
                skipped.append({"session_id": member["id"],
                                "reason": str(exc)})
        closed = self._groups.close_group(group_id, utc_now_iso())
        return {"group": self._enrich(closed), "ended": ended,
                "skipped": skipped}

    def get(self, group_id: str) -> dict:
        group = self._groups.get_group(group_id)
        if group is None:
            raise NotFound("Group not found")
        return self._enrich(group)

    def list_open(self) -> list[dict]:
        return [self._enrich(g) for g in self._groups.list_open()]

    def _require_open(self, group_id: str) -> dict:
        group = self._groups.get_group(group_id)
        if group is None:
            raise NotFound("Group not found")
        if group["status"] != SessionGroupStatus.OPEN.value:
            raise InvalidState(f"Group is {group['status']}")
        return group

    def _enrich(self, group: dict) -> dict:
        group = dict(group)
        group["members"] = self._groups.members(group["id"])
        return group
