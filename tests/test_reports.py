import uuid
from datetime import UTC, datetime

from gamenet.server.db import to_utc_iso


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return to_utc_iso(datetime.now(UTC))


def _customer(client, headers):
    r = client.post(
        "/api/v1/customers",
        json={"name": _uniq("Cust"), "pin": "1234"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _pc(client, headers):
    code = _uniq("PC")
    return client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=headers,
    ).json()


def _confirmed_sale(client, headers, customer_id, items):
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": customer_id, "items": items},
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": sale["total"]},
        headers=headers,
    )
    client.post(f"/api/v1/sales/{sale['id']}/confirm", headers=headers)
    return sale


def _ensure_open_shift(client, headers):
    r = client.post("/api/v1/shifts/open", json={"opening_float": 0},
                    headers=headers)
    assert r.status_code in (201, 409), r.text


def _close_current_shift(client, headers):
    current = client.get("/api/v1/shifts/current",
                         headers=headers).json()
    if current["status"] == "OPEN":
        client.post(
            "/api/v1/shifts/current/close",
            json={"counted_cash": current.get("expected_cash") or 0,
                  "note": "report test cleanup"},
            headers=headers,
        )


def test_sales_summary_totals_and_invariants(client, owner_headers):
    cust = _customer(client, owner_headers)
    t0 = _now()
    s1 = _confirmed_sale(client, owner_headers, cust["id"],
                         [{"kind": "TIME", "duration_sec": 3600}])
    s2 = _confirmed_sale(client, owner_headers, cust["id"],
                         [{"kind": "RECHARGE", "unit_price": 200000}])
    _ensure_open_shift(client, owner_headers)
    refund = client.post(
        f"/api/v1/sales/{s1['id']}/refunds",
        json={"amount": 10000, "method": "CASH",
              "reason": "report test"},
        headers=owner_headers,
    )
    assert refund.status_code == 201, refund.text
    t1 = _now()
    summary = client.get(
        "/api/v1/reports/sales-summary",
        params={"from_date": t0, "to_date": t1},
        headers=owner_headers).json()
    assert summary["count"] >= 2
    assert summary["gross"] >= s1["total"] + s2["total"]
    assert summary["refund_total"] >= 10000
    assert summary["net"] == summary["gross"] - summary["refund_total"]
    assert summary["by_method"].get("CASH", 0) >= s1["total"] + s2[
        "total"]
    assert any(op["count"] >= 2 for op in summary["by_operator"])
    _close_current_shift(client, owner_headers)


def test_sales_window_excludes_and_validates(client, owner_headers):
    empty = client.get(
        "/api/v1/reports/sales-summary",
        params={"from_date": "2999-01-01T00:00:00Z"},
        headers=owner_headers).json()
    assert empty["count"] == 0
    assert empty["gross"] == 0
    assert empty["net"] == 0
    bad = client.get(
        "/api/v1/reports/sales-summary",
        params={"from_date": "tomorrow-ish"},
        headers=owner_headers)
    assert bad.status_code == 422
    flipped = client.get(
        "/api/v1/reports/sales-summary",
        params={"from_date": "2027-01-02T00:00:00Z",
                "to_date": "2027-01-01T00:00:00Z"},
        headers=owner_headers)
    assert flipped.status_code == 422


def test_shift_report_lists_open_shift(client, owner_headers):
    _ensure_open_shift(client, owner_headers)
    report = client.get("/api/v1/reports/shifts",
                        headers=owner_headers).json()
    assert any(s["status"] == "OPEN" for s in report["shifts"])
    _close_current_shift(client, owner_headers)


def test_utilization_counts_session(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _confirmed_sale(client, owner_headers, cust["id"],
                    [{"kind": "TIME", "duration_sec": 3600}])
    s = client.post(
        "/api/v1/sessions",
        json={"customer_id": cust["id"], "pc_id": pc["id"]},
        headers=owner_headers,
    ).json()
    client.post(f"/api/v1/sessions/{s['id']}/authorize", json={},
                headers=owner_headers)
    client.post(f"/api/v1/sessions/{s['id']}/start",
                headers=owner_headers)
    client.post(f"/api/v1/sessions/{s['id']}/end", json={},
                headers=owner_headers)
    util = client.get("/api/v1/reports/utilization",
                      headers=owner_headers).json()
    mine = [p for p in util["pcs"] if p["pc_id"] == pc["id"]]
    assert len(mine) == 1
    assert mine[0]["sessions"] >= 1
    assert mine[0]["active_sec"] >= 0


def test_inventory_report_flags_low_stock(client, owner_headers):
    sku = _uniq("SKU")
    item = client.post(
        "/api/v1/inventory/items",
        json={"sku": sku, "name": sku, "unit_price": 50000,
              "low_stock_at": 5},
        headers=owner_headers,
    )
    assert item.status_code == 201, item.text
    report = client.get("/api/v1/reports/inventory",
                        headers=owner_headers).json()
    mine = [i for i in report["items"] if i["sku"] == sku]
    assert len(mine) == 1
    assert mine[0]["is_low"] is True
    assert sku in [i["sku"] for i in report["low_stock"]]


def test_export_csv_and_unknown_type(client, owner_headers):
    csv_resp = client.get(
        "/api/v1/reports/export", params={"type": "sales"},
        headers=owner_headers)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "attachment" in csv_resp.headers["content-disposition"]
    first_line = csv_resp.text.splitlines()[0]
    assert "customer_id" in first_line
    assert "total" in first_line
    unknown = client.get("/api/v1/reports/export",
                         params={"type": "nope"},
                         headers=owner_headers)
    assert unknown.status_code == 422


def test_reports_permissions(client, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert client.get("/api/v1/reports/utilization",
                      headers=viewer).status_code == 200
    assert client.get("/api/v1/reports/inventory",
                      headers=viewer).status_code == 200
    assert client.get("/api/v1/reports/sales-summary",
                      headers=viewer).status_code == 403
    assert client.get("/api/v1/reports/shifts",
                      headers=viewer).status_code == 403
    assert client.get("/api/v1/reports/export",
                      params={"type": "sales"},
                      headers=viewer).status_code == 403
