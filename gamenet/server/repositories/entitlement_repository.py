import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


class EntitlementRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        *,
        entitlement_id: str,
        customer_id: str,
        kind: str,
        status: str,
        granted_sec: int | None = None,
        starts_at: str,
        expires_at: str | None = None,
        discount_pct: int = 0,
        sale_id: str | None = None,
        sale_item_id: str | None = None,
        ref_id: str | None = None,
    ) -> dict:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO entitlements (id, customer_id, kind, status, granted_sec,
                                      consumed_sec, starts_at, expires_at,
                                      discount_pct, sale_id, sale_item_id, ref_id,
                                      created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entitlement_id, customer_id, kind, status, granted_sec,
                starts_at, expires_at, discount_pct, sale_id, sale_item_id,
                ref_id, now, now,
            ),
        )
        return self.get(entitlement_id)

    def get(self, entitlement_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM entitlements WHERE id = ?", (entitlement_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_for_customer(
        self, customer_id: str, *, kinds: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM entitlements WHERE customer_id = ?"
        params: list = [customer_id]
        if kinds:
            sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
            params.extend(kinds)
        if statuses:
            sql += f" AND status IN ({', '.join('?' for _ in statuses)})"
            params.extend(statuses)
        sql += " ORDER BY created_at"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def set_status(self, entitlement_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE entitlements SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_iso(), entitlement_id),
        )

    def add_consumed(self, entitlement_id: str, seconds: int) -> dict:
        self._conn.execute(
            "UPDATE entitlements SET consumed_sec = consumed_sec + ?, updated_at = ? WHERE id = ?",
            (seconds, utc_now_iso(), entitlement_id),
        )
        return self.get(entitlement_id)

    def list_for_sale(self, sale_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM entitlements WHERE sale_id = ? ORDER BY rowid",
            (sale_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def revoke_grant(self, entitlement_id: str, seconds: int) -> dict:
        """Shrink a grant (refunds); never below what was consumed."""
        self._conn.execute(
            """UPDATE entitlements
               SET granted_sec = MAX(consumed_sec, granted_sec - ?),
                   updated_at = ?
               WHERE id = ?""",
            (seconds, utc_now_iso(), entitlement_id),
        )
        return self.get(entitlement_id)

    def append_ledger(
        self,
        *,
        entitlement_id: str,
        delta_sec: int,
        kind: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        reason: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        row = self._conn.execute(
            "SELECT consumed_sec, granted_sec FROM entitlements WHERE id = ?",
            (entitlement_id,),
        ).fetchone()
        granted = row["granted_sec"] or 0
        balance_after = granted - (row["consumed_sec"] or 0)
        entry_id = f"ELED-{uuid.uuid4().hex[:12].upper()}"
        self._conn.execute(
            """
            INSERT INTO entitlement_ledger (id, entitlement_id, delta_sec,
                                            balance_after_sec, kind, ref_type,
                                            ref_id, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id, entitlement_id, delta_sec, balance_after, kind,
                ref_type, ref_id, reason, created_by, utc_now_iso(),
            ),
        )
        entry = self._conn.execute(
            "SELECT * FROM entitlement_ledger WHERE id = ?", (entry_id,)
        ).fetchone()
        return dict(entry)

    def ledger_for_customer(self, customer_id: str, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT l.* FROM entitlement_ledger l
            JOIN entitlements e ON e.id = l.entitlement_id
            WHERE e.customer_id = ?
            ORDER BY l.created_at DESC LIMIT ?
            """,
            (customer_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
