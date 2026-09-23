"""Startup recovery checks (Master Spec 225-229, 145).

- Verifies database integrity; on failure the server enables safe mode
  automatically so no new financial operation is accepted (Spec 145).
- Reports counts an operator should look at (UNKNOWN payments, live sessions).
"""

import sqlite3

from gamenet.server.repositories.settings_repository import SettingsRepository


def startup_checks(conn: sqlite3.Connection | None = None) -> dict:
    from gamenet.server.db import connect

    own = conn is None
    conn = conn or connect()
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        ok = integrity == "ok"
        unknown = conn.execute(
            "SELECT COUNT(*) AS c FROM payments WHERE status = 'UNKNOWN'"
        ).fetchone()["c"]
        active_sessions = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE status IN "
            "('AUTHORIZED', 'ACTIVE', 'PAUSED', 'INTERRUPTED', 'CONNECTION_LOST')"
        ).fetchone()["c"]
        draft_with_money = conn.execute(
            """
            SELECT COUNT(DISTINCT s.id) AS c FROM sales s
            JOIN payments p ON p.sale_id = s.id
            WHERE s.status = 'DRAFT' AND p.status IN ('PAID', 'UNKNOWN', 'PROCESSING', 'PENDING')
            """
        ).fetchone()["c"]
        if not ok:
            repo = SettingsRepository(conn)
            repo.set("safe_mode", "1")
            repo.set("safe_mode_reason", f"integrity_check failed: {str(integrity)[:200]}")
        return {
            "integrity_ok": ok,
            "unknown_payments": int(unknown),
            "active_sessions": int(active_sessions),
            "draft_sales_with_payments": int(draft_with_money),
            "safe_mode": not ok,
        }
    finally:
        if own:
            conn.commit()
            conn.close()
