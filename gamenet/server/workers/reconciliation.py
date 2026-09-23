"""Reconciliation engine (Master Spec 337-338).

Cross-checks every money/time relationship and stores each run so the
owner can see WHEN the system was last proven consistent and WHAT broke.
"""

import json
import sqlite3
import uuid

from gamenet.server.db import utc_now_iso


def _issue(check: str, entity: str, detail: str) -> dict:
    return {"check": check, "entity": entity, "detail": detail}


def run_reconciliation(
    conn: sqlite3.Connection, *, triggered_by: str | None = None
) -> dict:
    started_at = utc_now_iso()
    issues: list[dict] = []
    issues += _check_balances(conn)
    issues += _check_entitlements(conn)
    issues += _check_sales(conn)
    issues += _check_confirmed_grants(conn)
    issues += _check_payments(conn)
    issues += _check_sessions(conn)
    finished_at = utc_now_iso()
    status = "OK" if not issues else "ISSUES"
    run_id = f"REC-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        """
        INSERT INTO reconciliation_runs (id, started_at, finished_at, status,
                                         issues_json, triggered_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, started_at, finished_at, status,
            json.dumps(issues, ensure_ascii=True), triggered_by, finished_at,
        ),
    )
    return {
        "id": run_id, "started_at": started_at, "finished_at": finished_at,
        "status": status, "issues": issues, "triggered_by": triggered_by,
    }


def latest_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM reconciliation_runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["issues"] = json.loads(run["issues_json"])
    return run


def _check_balances(conn: sqlite3.Connection) -> list[dict]:
    issues = []
    sums = {
        r["customer_id"]: r["s"]
        for r in conn.execute(
            "SELECT customer_id, COALESCE(SUM(amount), 0) AS s "
            "FROM customer_balance_ledger GROUP BY customer_id"
        ).fetchall()
    }
    lasts = conn.execute(
        """
        SELECT customer_id, balance_after FROM customer_balance_ledger
        WHERE rowid IN (SELECT MAX(rowid) FROM customer_balance_ledger
                        GROUP BY customer_id)
        """
    ).fetchall()
    for row in lasts:
        if int(row["balance_after"]) != int(sums.get(row["customer_id"], 0)):
            issues.append(_issue(
                "balance_ledger", row["customer_id"],
                f"balance_after={row['balance_after']} != sum={sums.get(row['customer_id'], 0)}",
            ))
    return issues


def _check_entitlements(conn: sqlite3.Connection) -> list[dict]:
    issues = []
    rows = conn.execute(
        """
        SELECT e.id, e.granted_sec, e.consumed_sec,
               COALESCE(SUM(CASE WHEN l.kind = 'CONSUME' THEN -l.delta_sec END), 0) AS c,
               COALESCE(SUM(CASE WHEN l.kind = 'GRANT' THEN l.delta_sec END), 0) AS g
        FROM entitlements e
        LEFT JOIN entitlement_ledger l ON l.entitlement_id = e.id
        GROUP BY e.id
        """
    ).fetchall()
    for row in rows:
        if int(row["consumed_sec"] or 0) != int(row["c"]):
            issues.append(_issue(
                "entitlement_consumed", row["id"],
                f"consumed_sec={row['consumed_sec']} != ledger={row['c']}",
            ))
        granted = row["granted_sec"]
        if granted is not None and int(granted) != int(row["g"]):
            issues.append(_issue(
                "entitlement_granted", row["id"],
                f"granted_sec={granted} != ledger grants={row['g']}",
            ))
    return issues


def _check_sales(conn: sqlite3.Connection) -> list[dict]:
    issues = []
    rows = conn.execute(
        """
        SELECT s.id, s.subtotal, s.discount_pct, s.discount_amount, s.total,
               COALESCE(SUM(i.total_price), 0) AS items
        FROM sales s LEFT JOIN sale_items i ON i.sale_id = s.id
        GROUP BY s.id
        """
    ).fetchall()
    for row in rows:
        if int(row["subtotal"]) != int(row["items"]):
            issues.append(_issue(
                "sale_subtotal", row["id"],
                f"subtotal={row['subtotal']} != items={row['items']}",
            ))
        expected_discount = (int(row["subtotal"]) * int(row["discount_pct"]) + 50) // 100
        if int(row["discount_amount"]) != expected_discount:
            issues.append(_issue(
                "sale_discount", row["id"],
                f"discount_amount={row['discount_amount']} != expected={expected_discount}",
            ))
        if int(row["total"]) != int(row["subtotal"]) - int(row["discount_amount"]):
            issues.append(_issue(
                "sale_total", row["id"],
                f"total={row['total']} != subtotal-discount",
            ))
    return issues


def _check_confirmed_grants(conn: sqlite3.Connection) -> list[dict]:
    issues = []
    missing_ents = conn.execute(
        """
        SELECT i.id, i.sale_id, i.kind FROM sale_items i
        JOIN sales s ON s.id = i.sale_id
        LEFT JOIN entitlements e ON e.sale_item_id = i.id
        WHERE s.status = 'CONFIRMED' AND i.kind IN ('TIME', 'PACKAGE', 'VIP')
          AND e.id IS NULL
        """
    ).fetchall()
    for row in missing_ents:
        issues.append(_issue(
            "activation_missing", row["sale_id"],
            f"{row['kind']} item {row['id']} has no entitlement",
        ))
    missing_recharge = conn.execute(
        """
        SELECT i.sale_id FROM sale_items i
        JOIN sales s ON s.id = i.sale_id
        LEFT JOIN customer_balance_ledger b
          ON b.ref_id = s.id AND b.kind = 'RECHARGE'
        WHERE s.status = 'CONFIRMED' AND i.kind = 'RECHARGE' AND b.id IS NULL
        """
    ).fetchall()
    for row in missing_recharge:
        issues.append(_issue(
            "activation_missing", row["sale_id"],
            "RECHARGE item has no balance grant",
        ))
    underpaid = conn.execute(
        """
        SELECT s.id, s.total, COALESCE(SUM(
            CASE WHEN p.status = 'PAID' THEN p.amount END), 0) AS paid
        FROM sales s LEFT JOIN payments p ON p.sale_id = s.id
        WHERE s.status = 'CONFIRMED'
        GROUP BY s.id HAVING paid != s.total
        """
    ).fetchall()
    for row in underpaid:
        issues.append(_issue(
            "confirmed_underpaid", row["id"],
            f"paid={row['paid']} != total={row['total']}",
        ))
    return issues


def _check_payments(conn: sqlite3.Connection) -> list[dict]:
    issues = []
    rows = conn.execute(
        "SELECT id FROM payments WHERE status = 'PAID' AND paid_at IS NULL"
    ).fetchall()
    for row in rows:
        issues.append(_issue("payment_paid_at", row["id"], "PAID without paid_at"))
    return issues


def _check_sessions(conn: sqlite3.Connection) -> list[dict]:
    issues = []
    rows = conn.execute(
        """
        SELECT s.id, s.total_consumed_sec, COALESCE(SUM(c.seconds), 0) AS c
        FROM sessions s
        LEFT JOIN session_consumptions c ON c.session_id = s.id
        GROUP BY s.id HAVING s.total_consumed_sec != c
        """
    ).fetchall()
    for row in rows:
        issues.append(_issue(
            "session_consumed", row["id"],
            f"total_consumed_sec={row['total_consumed_sec']} != consumptions={row['c']}",
        ))
    return issues
