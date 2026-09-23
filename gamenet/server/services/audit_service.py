"""Audit log writer (Master Spec 95-98) with tamper-evident hash chain (295).

Each row links to the previous row's hash; ``verify_audit_chain`` recomputes
every link so any later modification (or deletion in the middle) is
detectable. Rows written before migration 008 have NULL hashes and are
reported as legacy/skipped by the verifier.
"""

import hashlib
import json
import sqlite3
import uuid

from gamenet.server.db import utc_now_iso

GENESIS_HASH = "GENESIS"


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _row_hash(prev_hash: str, fields: dict) -> str:
    return hashlib.sha256(
        _canonical({"prev_hash": prev_hash, **fields}).encode("utf-8")
    ).hexdigest()


def log_audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    user_id: str | None = None,
    role_name: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    amount: int | None = None,
    pc_id: str | None = None,
    customer_id: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> dict:
    audit_id = f"AUDIT-{uuid.uuid4().hex[:12].upper()}"
    timestamp = utc_now_iso()
    last = conn.execute(
        "SELECT hash FROM audit_logs WHERE hash IS NOT NULL "
        "ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    prev_hash = last["hash"] if last else GENESIS_HASH
    fields = {
        "timestamp": timestamp, "user_id": user_id, "role_name": role_name,
        "action": action, "entity_type": entity_type, "entity_id": entity_id,
        "old_value": old_value, "new_value": new_value, "amount": amount,
        "pc_id": pc_id, "customer_id": customer_id, "reason": reason,
        "request_id": request_id, "ip_address": ip_address,
    }
    row_hash = _row_hash(prev_hash, fields)
    conn.execute(
        """
        INSERT INTO audit_logs (
            id, timestamp, user_id, role_name, action, entity_type, entity_id,
            old_value, new_value, amount, pc_id, customer_id, reason,
            request_id, ip_address, prev_hash, hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id, timestamp, user_id, role_name, action, entity_type,
            entity_id, old_value, new_value, amount, pc_id, customer_id,
            reason, request_id, ip_address, prev_hash, row_hash,
        ),
    )
    row = conn.execute("SELECT * FROM audit_logs WHERE id = ?", (audit_id,)).fetchone()
    return dict(row)


def verify_audit_chain(conn: sqlite3.Connection) -> dict:
    """Recompute every hash link. Returns checked/skipped/ok/broken_id."""
    rows = conn.execute(
        "SELECT * FROM audit_logs ORDER BY rowid"
    ).fetchall()
    checked = 0
    skipped = 0
    expected_prev = GENESIS_HASH
    started = False
    for row in rows:
        if not row["hash"]:
            skipped += 1
            continue
        fields = {
            "timestamp": row["timestamp"], "user_id": row["user_id"],
            "role_name": row["role_name"], "action": row["action"],
            "entity_type": row["entity_type"], "entity_id": row["entity_id"],
            "old_value": row["old_value"], "new_value": row["new_value"],
            "amount": row["amount"], "pc_id": row["pc_id"],
            "customer_id": row["customer_id"], "reason": row["reason"],
            "request_id": row["request_id"], "ip_address": row["ip_address"],
        }
        if started and row["prev_hash"] != expected_prev:
            return {"checked": checked, "skipped": skipped, "ok": False,
                    "broken_id": row["id"], "reason": "link mismatch"}
        if _row_hash(row["prev_hash"], fields) != row["hash"]:
            return {"checked": checked, "skipped": skipped, "ok": False,
                    "broken_id": row["id"], "reason": "hash mismatch"}
        expected_prev = row["hash"]
        started = True
        checked += 1
    return {"checked": checked, "skipped": skipped, "ok": True,
            "broken_id": None, "reason": None}
