"""Lease monitor: pause-on-disconnect + periodic presence flush (P2-3).

Master Spec: lease expiry pauses the session (137/330); the agent shows
disconnect UI and waits for manual resume (15, 21-23). Runs as a daemon
thread in production (see main.lifespan); tests call `check_leases`
directly with a fake clock.
"""

from __future__ import annotations

import sqlite3
import threading
import time

from gamenet.server.db import get_connection, utc_now_iso
from gamenet.server.realtime import presence
from gamenet.server.repositories.session_repository import SessionRepository
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.session_service import SessionService

# PCs already auto-paused for their *current* outage (so each tick does not
# re-pause / re-queue LOCK). Cleared per-PC as soon as it beats again.
_handled: set[str] = set()
_handled_lock = threading.Lock()


def check_leases(conn: sqlite3.Connection,
                 now_ts: float | None = None) -> dict:
    now_ts = now_ts if now_ts is not None else time.time()
    summary: dict = {"checked": 0, "paused": [], "failed": [],
                     "flushed": 0}
    sessions = SessionRepository(conn)
    for rec in presence.snapshot():
        if rec.lease_until > now_ts:
            with _handled_lock:
                _handled.discard(rec.pc_id)
            continue
        summary["checked"] += 1
        with _handled_lock:
            if rec.pc_id in _handled:
                continue
            _handled.add(rec.pc_id)
        live = sessions.active_for_pc(rec.pc_id)
        if live is None or live["status"] != "ACTIVE":
            continue
        try:
            SessionService(conn).pause(
                live["id"], reason="LINK_LOST", actor_user_id=None
            )
            summary["paused"].append(live["id"])
        except (InvalidState, NotFound, ValueError) as exc:
            summary["failed"].append(
                {"session_id": live["id"], "error": str(exc)})
    summary["flushed"] = presence.flush_to_db(conn, utc_now_iso())
    return summary


def reset_handled() -> None:
    """Test helper: forget which PCs were already auto-paused."""
    with _handled_lock:
        _handled.clear()


def start_loop(interval_sec: int = 10) -> threading.Event:
    """Start the daemon monitor thread. Returns the stop event."""
    stop = threading.Event()

    def _run() -> None:
        while not stop.wait(interval_sec):
            try:
                with get_connection() as conn:
                    check_leases(conn)
            except Exception:
                # The monitor must never take the server down; an error
                # just means this tick is skipped (next tick retries).
                continue

    thread = threading.Thread(target=_run, name="lease-monitor",
                              daemon=True)
    thread.start()
    return stop
