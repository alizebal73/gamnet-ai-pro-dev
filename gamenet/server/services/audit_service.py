"""Audit log writer (Master Spec 95-98).

Every sensitive action must leave a row in ``audit_logs``. Audit rows are
append-only: this module deliberately offers no update/delete function.
"""

import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


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
    conn.execute(
        """
        INSERT INTO audit_logs (
            id, timestamp, user_id, role_name, action, entity_type, entity_id,
            old_value, new_value, amount, pc_id, customer_id, reason,
            request_id, ip_address
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id, utc_now_iso(), user_id, role_name, action, entity_type,
            entity_id, old_value, new_value, amount, pc_id, customer_id,
            reason, request_id, ip_address,
        ),
    )
    row = conn.execute("SELECT * FROM audit_logs WHERE id = ?", (audit_id,)).fetchone()
    return dict(row)
