"""Alert evaluation + inbox (P4-2).

`evaluate()` runs the health checks, opens alerts for new conditions
(deduplicated on source + entity while OPEN/ACKED), auto-resolves the
ones that cleared, and returns both sets. Telegram fan-out for new
WARNING/CRITICAL alerts happens in the API layer.
"""

import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from gamenet.server.db import to_utc_iso, utc_now_iso
from gamenet.server.repositories.settings_repository import (
    SettingsRepository,
)
from gamenet.server.services.errors import InvalidState, NotFound

STATUSES = ("OPEN", "ACKED", "RESOLVED")


class AlertService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._settings = SettingsRepository(conn)

    # ---------- inbox ----------

    def list_alerts(
            self, status: str | None = None) -> list[dict]:
        if status is not None and status not in STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        if status:
            rows = self._conn.execute(
                "SELECT * FROM alerts WHERE status = ? "
                "ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get(self, alert_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            raise NotFound("Alert not found")
        return dict(row)

    def ack(self, alert_id: str, user_id: str) -> dict:
        alert = self.get(alert_id)
        if alert["status"] != "OPEN":
            raise InvalidState(
                f"Alert is {alert['status']}, cannot ack")
        now = utc_now_iso()
        self._conn.execute(
            "UPDATE alerts SET status = 'ACKED', acked_at = ?, "
            "acked_by = ? WHERE id = ?",
            (now, user_id, alert_id),
        )
        return self.get(alert_id)

    def resolve(self, alert_id: str,
                user_id: str | None = None) -> dict:
        alert = self.get(alert_id)
        if alert["status"] == "RESOLVED":
            raise InvalidState("Alert is already resolved")
        self._conn.execute(
            "UPDATE alerts SET status = 'RESOLVED', resolved_at = ? "
            "WHERE id = ?",
            (utc_now_iso(), alert_id),
        )
        return self.get(alert_id)

    # ---------- evaluation ----------

    def evaluate(self) -> dict:
        conditions = [
            *self._check_disk(),
            *self._check_pcs(),
            *self._check_shifts(),
            *self._check_logins(),
            *self._check_stock(),
        ]
        live = {(c["source"], c["entity_type"], c["entity_id"])
                for c in conditions}
        existing = {
            (r["source"], r["entity_type"], r["entity_id"]): r["id"]
            for r in self._conn.execute(
                "SELECT * FROM alerts WHERE status IN ('OPEN', 'ACKED')"
            ).fetchall()
        }
        created = []
        for cond in conditions:
            key = (cond["source"], cond["entity_type"], cond["entity_id"])
            if key in existing:
                continue
            created.append(self._open(**cond))
        resolved = []
        for key, alert_id in existing.items():
            if key not in live:
                self.resolve(alert_id)
                resolved.append(alert_id)
        return {"created": created, "resolved": resolved}

    def _open(self, *, source: str, severity: str, title: str,
              detail: str | None = None,
              entity_type: str | None = None,
              entity_id: str | None = None) -> dict:
        alert_id = f"ALR-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """INSERT INTO alerts (id, severity, source, title, detail,
                                   entity_type, entity_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (alert_id, severity, source, title, detail, entity_type,
             entity_id, utc_now_iso()),
        )
        return self.get(alert_id)

    def _check_disk(self) -> list[dict]:
        minimum = self._settings.get_int("alert_disk_min_mb", 2048)
        free_mb = shutil.disk_usage(os.getcwd()).free // (1024 * 1024)
        if free_mb >= minimum:
            return []
        return [{
            "source": "SERVER_DISK", "severity": "CRITICAL",
            "title": f"Server disk low: {free_mb} MB free",
            "detail": f"Free space {free_mb} MB is below the "
                      f"{minimum} MB threshold.",
            "entity_type": "server", "entity_id": "disk",
        }]

    def _check_pcs(self) -> list[dict]:
        minutes = self._settings.get_int("alert_pc_offline_min", 10)
        cutoff = to_utc_iso(datetime.now(timezone.utc)
                            - timedelta(minutes=minutes))
        rows = self._conn.execute(
            """SELECT id, display_name FROM pcs
               WHERE status NOT IN ('RETIRED', 'MAINTENANCE')
                 AND (last_seen_at IS NULL OR last_seen_at < ?)""",
            (cutoff,),
        ).fetchall()
        return [{
            "source": "PC_OFFLINE", "severity": "WARNING",
            "title": f"PC offline: {r['display_name']}",
            "detail": f"No heartbeat for over {minutes} minutes.",
            "entity_type": "pc", "entity_id": r["id"],
        } for r in rows]

    def _check_shifts(self) -> list[dict]:
        hours = self._settings.get_int("alert_shift_max_hours", 16)
        cutoff = to_utc_iso(datetime.now(timezone.utc)
                            - timedelta(hours=hours))
        rows = self._conn.execute(
            "SELECT id, opened_at FROM shifts "
            "WHERE status = 'OPEN' AND opened_at < ?",
            (cutoff,),
        ).fetchall()
        return [{
            "source": "SHIFT_STUCK", "severity": "WARNING",
            "title": f"Shift open too long: {r['id']}",
            "detail": f"Open since {r['opened_at']} "
                      f"(over {hours}h).",
            "entity_type": "shift", "entity_id": r["id"],
        } for r in rows]

    def _check_logins(self) -> list[dict]:
        threshold = self._settings.get_int("alert_login_spike", 10)
        window = self._settings.get_int("alert_login_window_min", 15)
        since = to_utc_iso(datetime.now(timezone.utc)
                           - timedelta(minutes=window))
        count = self._conn.execute(
            "SELECT COUNT(*) AS n FROM audit_logs "
            "WHERE action = 'LOGIN_FAILED' AND timestamp >= ?",
            (since,),
        ).fetchone()["n"]
        if count < threshold:
            return []
        return [{
            "source": "LOGIN_SPIKE", "severity": "WARNING",
            "title": f"Failed-login spike: {count} in {window} min",
            "detail": f"{count} failed logins since {since} "
                      f"(threshold {threshold}).",
            "entity_type": "global", "entity_id": "logins",
        }]

    def _check_stock(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT id, sku, name FROM inventory_items
               WHERE status = 'ACTIVE' AND stock_qty <= low_stock_at"""
        ).fetchall()
        return [{
            "source": "LOW_STOCK", "severity": "INFO",
            "title": f"Low stock: {r['name']}",
            "detail": f"SKU {r['sku']} at or below reorder level.",
            "entity_type": "inventory_item", "entity_id": r["id"],
        } for r in rows]
