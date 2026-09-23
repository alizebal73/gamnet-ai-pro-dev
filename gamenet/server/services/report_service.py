"""Read-only operational reports (P4-1).

All money figures are in the smallest currency unit. Date windows are
ISO-8601 strings compared lexicographically against the UTC `Z`-suffixed
timestamps the rest of the system writes.
"""

import csv
import io
import sqlite3
from datetime import datetime


def _check_window(from_date: str | None,
                  to_date: str | None) -> tuple[str | None, str | None]:
    for value in (from_date, to_date):
        if value is None:
            continue
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid ISO date: {value!r}")
    if from_date and to_date and to_date < from_date:
        raise ValueError("to_date must not be before from_date")
    return from_date, to_date


def _between(column: str, from_date: str | None,
             to_date: str | None) -> tuple[str, list]:
    clauses: list = []
    params: list = []
    if from_date:
        clauses.append(f"{column} >= ?")
        params.append(from_date)
    if to_date:
        clauses.append(f"{column} <= ?")
        params.append(to_date)
    return (" AND ".join(clauses) if clauses else "1 = 1"), params


class ReportService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ---------- sales ----------

    def sales_summary(self, from_date: str | None = None,
                      to_date: str | None = None) -> dict:
        from_date, to_date = _check_window(from_date, to_date)
        where, params = _between("confirmed_at", from_date, to_date)
        row = self._conn.execute(
            f"""SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS gross,
                       COALESCE(SUM(discount_amount), 0) AS discounts
                FROM sales WHERE status = 'CONFIRMED' AND {where}""",
            params,
        ).fetchone()
        rwhere, rparams = _between("created_at", from_date, to_date)
        refunds = self._conn.execute(
            f"""SELECT COALESCE(SUM(amount), 0) AS total FROM refunds
                WHERE {rwhere}""",
            rparams,
        ).fetchone()["total"]
        by_method = {
            r["method"]: r["total"]
            for r in self._conn.execute(
                f"""SELECT p.method AS method, SUM(p.amount) AS total
                    FROM payments p JOIN sales s ON s.id = p.sale_id
                    WHERE s.status = 'CONFIRMED' AND p.paid_at IS NOT NULL
                      AND {where.replace('confirmed_at', 's.confirmed_at')}
                    GROUP BY p.method""",
                params,
            ).fetchall()
        }
        by_operator = [
            {"operator_user_id": r["op"], "count": r["n"],
             "gross": r["gross"]}
            for r in self._conn.execute(
                f"""SELECT operator_user_id AS op, COUNT(*) AS n,
                           COALESCE(SUM(total), 0) AS gross
                    FROM sales WHERE status = 'CONFIRMED' AND {where}
                    GROUP BY operator_user_id""",
                params,
            ).fetchall()
        ]
        return {
            "from_date": from_date, "to_date": to_date,
            "count": row["n"], "gross": row["gross"],
            "discount_total": row["discounts"],
            "refund_total": refunds,
            "net": row["gross"] - refunds,
            "by_method": by_method, "by_operator": by_operator,
        }

    def shift_report(self, from_date: str | None = None,
                     to_date: str | None = None) -> dict:
        from_date, to_date = _check_window(from_date, to_date)
        where, params = _between("opened_at", from_date, to_date)
        shifts = [
            dict(r) for r in self._conn.execute(
                f"SELECT * FROM shifts WHERE {where} ORDER BY opened_at",
                params,
            ).fetchall()
        ]
        return {"shifts": shifts}

    # ---------- utilization ----------

    def utilization(self, from_date: str | None = None,
                    to_date: str | None = None) -> dict:
        from_date, to_date = _check_window(from_date, to_date)
        where, params = _between("s.created_at", from_date, to_date)
        pcs = [
            {
                "pc_id": r["pc_id"],
                "active_sec": r["active_sec"],
                "sessions": r["sessions"],
                "customers": r["customers"],
            }
            for r in self._conn.execute(
                f"""SELECT s.pc_id AS pc_id,
                           COALESCE(SUM(c.seconds), 0) AS active_sec,
                           COUNT(DISTINCT s.id) AS sessions,
                           COUNT(DISTINCT s.customer_id) AS customers
                    FROM sessions s
                    LEFT JOIN session_consumptions c
                      ON c.session_id = s.id
                    WHERE {where}
                    GROUP BY s.pc_id""",
                params,
            ).fetchall()
        ]
        return {"pcs": pcs}

    # ---------- inventory ----------

    def inventory_report(self) -> dict:
        items = [dict(r) for r in self._conn.execute(
            "SELECT * FROM inventory_items ORDER BY sku").fetchall()]
        for item in items:
            item["stock_value"] = (
                item["stock_qty"] * item["unit_price"])
            item["is_low"] = (
                item["status"] == "ACTIVE"
                and item["stock_qty"] <= item["low_stock_at"])
        stock_value = sum(i["stock_value"] for i in items)
        low_stock = [i for i in items if i["is_low"]]
        return {"items": items, "stock_value": stock_value,
                "low_stock": low_stock}

    # ---------- CSV export ----------

    _EXPORTS = {
        "sales": (
            ["id", "customer_id", "status", "subtotal", "discount_amount",
             "total", "operator_user_id", "confirmed_at"],
            "SELECT id, customer_id, status, subtotal, discount_amount, "
            "total, operator_user_id, confirmed_at FROM sales "
            "WHERE status = 'CONFIRMED' AND {where} ORDER BY confirmed_at",
            "confirmed_at",
        ),
        "shifts": (
            ["id", "status", "opened_by", "opened_at", "closed_by",
             "closed_at", "opening_float", "expected_cash",
             "counted_cash", "variance"],
            "SELECT id, status, opened_by, opened_at, closed_by, "
            "closed_at, opening_float, expected_cash, counted_cash, "
            "variance FROM shifts WHERE {where} ORDER BY opened_at",
            "opened_at",
        ),
        "sessions": (
            ["id", "pc_id", "customer_id", "status", "created_at"],
            "SELECT id, pc_id, customer_id, status, created_at FROM "
            "sessions WHERE {where} ORDER BY created_at",
            "created_at",
        ),
        "inventory": (
            ["sku", "name", "stock_qty", "unit_price", "low_stock_at",
             "status"],
            "SELECT sku, name, stock_qty, unit_price, low_stock_at, "
            "status FROM inventory_items ORDER BY sku",
            None,
        ),
    }

    def export_csv(self, kind: str, from_date: str | None = None,
                   to_date: str | None = None) -> tuple[str, str]:
        if kind not in self._EXPORTS:
            raise ValueError(
                f"Unknown export type: {kind!r} "
                f"(want one of {sorted(self._EXPORTS)})")
        from_date, to_date = _check_window(from_date, to_date)
        header, sql, column = self._EXPORTS[kind]
        if column:
            where, params = _between(column, from_date, to_date)
            sql = sql.format(where=where)
        else:
            params = []
        rows = self._conn.execute(sql, params).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        for row in rows:
            writer.writerow([(row[c] if row[c] is not None else "")
                             for c in header])
        return f"{kind}-export.csv", buf.getvalue()
