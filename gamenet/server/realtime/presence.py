"""PC presence + lease tracking (Master Spec 12-24, 137, 330).

Single-writer in-memory registry guarded by a lock. A heartbeat refreshes
`last_seen` and extends the lease; anything whose lease lapses is treated
as disconnected (the lease monitor in P2-3 pauses its session).
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field


@dataclass
class PresenceRecord:
    pc_id: str
    last_seen: float
    lease_until: float
    agent_version: str | None = None
    session_id: str | None = None
    ip: str | None = None
    extra: dict = field(default_factory=dict)


_lock = threading.Lock()
_records: dict[str, PresenceRecord] = {}


def record_heartbeat(
    pc_id: str,
    now_ts: float,
    lease_sec: int,
    agent_version: str | None = None,
    session_id: str | None = None,
    ip: str | None = None,
    extra: dict | None = None,
) -> PresenceRecord:
    with _lock:
        rec = _records.get(pc_id)
        if rec is None:
            rec = PresenceRecord(pc_id=pc_id, last_seen=now_ts,
                                 lease_until=now_ts + lease_sec)
            _records[pc_id] = rec
        rec.last_seen = now_ts
        rec.lease_until = now_ts + lease_sec
        if agent_version is not None:
            rec.agent_version = agent_version
        if session_id is not None:
            rec.session_id = session_id
        if ip is not None:
            rec.ip = ip
        if extra:
            rec.extra.update(extra)
        return rec


def get(pc_id: str) -> PresenceRecord | None:
    with _lock:
        return _records.get(pc_id)


def is_online(pc_id: str, now_ts: float) -> bool:
    with _lock:
        rec = _records.get(pc_id)
        return rec is not None and rec.lease_until > now_ts


def expired_leases(now_ts: float) -> list[PresenceRecord]:
    with _lock:
        return [r for r in _records.values() if r.lease_until <= now_ts]


def mark_offline(pc_id: str) -> None:
    with _lock:
        _records.pop(pc_id, None)


def online_pcs(now_ts: float) -> list[PresenceRecord]:
    with _lock:
        return [r for r in _records.values() if r.lease_until > now_ts]


def snapshot() -> list[PresenceRecord]:
    with _lock:
        return list(_records.values())


def reset() -> None:
    """Test helper: drop all in-memory presence."""
    with _lock:
        _records.clear()


def flush_to_db(conn: sqlite3.Connection, now_iso: str) -> int:
    """Persist last-seen info to `pcs` (called periodically, not per beat)."""
    with _lock:
        recs = list(_records.values())
    for rec in recs:
        conn.execute(
            """UPDATE pcs SET last_seen_at = ?, agent_version = COALESCE(?, agent_version),
                              updated_at = ? WHERE id = ?""",
            (now_iso, rec.agent_version, now_iso, rec.pc_id),
        )
    return len(recs)
