import uuid

from gamenet.server.db import get_connection


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _customer(client, headers):
    r = client.post(
        "/api/v1/customers",
        json={"name": _uniq("Cust"), "pin": "1234"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _item(client, headers, stock=0, price=25000, low=0, sku=None):
    r = client.post(
        "/api/v1/inventory/items",
        json={"sku": sku or _uniq("SKU"), "name": _uniq("Snack"),
              "unit_price": price, "low_stock_at": low},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    item = r.json()
    if stock:
        rcv = client.post(
            f"/api/v1/inventory/items/{item['id']}/receive",
            json={"qty": stock, "reason": "test supply"},
            headers=headers,
        )
        assert rcv.status_code == 200, rcv.text
        item = rcv.json()
    return item


def _confirm_food(client, headers, customer_id, item_id, qty):
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": customer_id,
              "items": [{"kind": "FOOD", "ref_id": item_id,
                         "qty": qty}]},
        headers=headers,
    )
    assert sale.status_code == 201, sale.text
    sale = sale.json()
    client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": sale["total"]},
        headers=headers,
    )
    done = client.post(f"/api/v1/sales/{sale['id']}/confirm",
                       headers=headers)
    assert done.status_code == 200, done.text
    return done.json()


def test_create_get_list_item(client, owner_headers):
    item = _item(client, owner_headers)
    assert item["id"].startswith("INV-")
    assert item["stock_qty"] == 0
    assert item["low_stock"] is False
    got = client.get(f"/api/v1/inventory/items/{item['id']}",
                     headers=owner_headers).json()
    assert got["sku"] == item["sku"]
    listed = client.get("/api/v1/inventory/items",
                        headers=owner_headers).json()
    assert item["id"] in [i["id"] for i in listed]
    assert client.get("/api/v1/inventory/items/INV-NOPE",
                      headers=owner_headers).status_code == 404


def test_duplicate_sku_rejected(client, owner_headers):
    first = _item(client, owner_headers, sku=_uniq("DUP"))
    again = client.post(
        "/api/v1/inventory/items",
        json={"sku": first["sku"], "name": "Other", "unit_price": 1},
        headers=owner_headers,
    )
    assert again.status_code == 409


def test_receive_and_ledger(client, owner_headers):
    item = _item(client, owner_headers, stock=10)
    assert item["stock_qty"] == 10
    ledger = client.get(
        f"/api/v1/inventory/items/{item['id']}/ledger",
        headers=owner_headers).json()
    assert ledger[0]["kind"] == "RECEIVE"
    assert ledger[0]["delta"] == 10
    assert ledger[0]["balance_after"] == 10


def test_adjust_and_negative_blocked(client, owner_headers):
    item = _item(client, owner_headers, stock=5)
    adj = client.post(
        f"/api/v1/inventory/items/{item['id']}/adjust",
        json={"delta": -2, "reason": "damaged pack"},
        headers=owner_headers,
    )
    assert adj.json()["stock_qty"] == 3
    bad = client.post(
        f"/api/v1/inventory/items/{item['id']}/adjust",
        json={"delta": -5, "reason": "too much"},
        headers=owner_headers,
    )
    assert bad.status_code == 409
    zero = client.post(
        f"/api/v1/inventory/items/{item['id']}/adjust",
        json={"delta": 0, "reason": "noop"},
        headers=owner_headers,
    )
    assert zero.status_code == 400


def test_inventory_permissions(client, owner_headers, make_user_with_token):
    item = _item(client, owner_headers, stock=2)
    operator = make_user_with_token("operator")
    assert client.post(
        "/api/v1/inventory/items",
        json={"sku": _uniq("S"), "name": "x", "unit_price": 1},
        headers=operator).status_code == 403
    assert client.get("/api/v1/inventory/items",
                      headers=operator).status_code == 200
    assert client.get(f"/api/v1/inventory/items/{item['id']}",
                      headers=operator).status_code == 200
    assert client.post(
        f"/api/v1/inventory/items/{item['id']}/receive",
        json={"qty": 1}, headers=operator).status_code == 403


def test_food_sale_flow(client, owner_headers):
    item = _item(client, owner_headers, stock=10, price=25000)
    cust = _customer(client, owner_headers)
    sale = _confirm_food(client, owner_headers, cust["id"],
                         item["id"], 3)
    assert sale["total"] == 75000
    got = client.get(f"/api/v1/inventory/items/{item['id']}",
                     headers=owner_headers).json()
    assert got["stock_qty"] == 7
    ledger = client.get(
        f"/api/v1/inventory/items/{item['id']}/ledger",
        headers=owner_headers).json()
    assert ledger[0]["kind"] == "SELL"
    assert ledger[0]["delta"] == -3
    assert ledger[0]["ref_id"] == sale["id"]


def test_food_oversell_rejected_at_draft(client, owner_headers):
    item = _item(client, owner_headers, stock=10)
    cust = _customer(client, owner_headers)
    r = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "FOOD", "ref_id": item["id"],
                         "qty": 11}]},
        headers=owner_headers,
    )
    assert r.status_code == 409
    missing = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "FOOD", "ref_id": "INV-NOPE",
                         "qty": 1}]},
        headers=owner_headers,
    )
    assert missing.status_code == 422


def test_food_confirm_time_race_refused(client, owner_headers):
    item = _item(client, owner_headers, stock=10)
    cust = _customer(client, owner_headers)
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "FOOD", "ref_id": item["id"],
                         "qty": 8}]},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/v1/inventory/items/{item['id']}/adjust",
        json={"delta": -5, "reason": "sold at kiosk"},
        headers=owner_headers,
    )
    client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": sale["total"]},
        headers=owner_headers,
    )
    done = client.post(f"/api/v1/sales/{sale['id']}/confirm",
                       headers=owner_headers)
    assert done.status_code == 409


def test_food_server_pricing_ignores_client(client, owner_headers):
    item = _item(client, owner_headers, stock=10, price=25000)
    cust = _customer(client, owner_headers)
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "FOOD", "ref_id": item["id"],
                         "qty": 2, "unit_price": 1}]},
        headers=owner_headers,
    )
    assert sale.status_code == 201, sale.text
    assert sale.json()["total"] == 50000


def test_archived_item_rejected_then_restored(client, owner_headers):
    item = _item(client, owner_headers, stock=10)
    cust = _customer(client, owner_headers)
    client.post(f"/api/v1/inventory/items/{item['id']}/archive",
                headers=owner_headers)
    r = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "FOOD", "ref_id": item["id"],
                         "qty": 1}]},
        headers=owner_headers,
    )
    assert r.status_code == 422
    client.post(f"/api/v1/inventory/items/{item['id']}/unarchive",
                headers=owner_headers)
    ok = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "FOOD", "ref_id": item["id"],
                         "qty": 1}]},
        headers=owner_headers,
    )
    assert ok.status_code == 201


def test_low_stock_flag_and_filter(client, owner_headers):
    low = _item(client, owner_headers, stock=3, low=5)
    assert low["low_stock"] is True
    plenty = _item(client, owner_headers, stock=10, low=5)
    assert plenty["low_stock"] is False
    only = client.get("/api/v1/inventory/items",
                      params={"low_only": True},
                      headers=owner_headers).json()
    ids = [i["id"] for i in only]
    assert low["id"] in ids
    assert plenty["id"] not in ids


def test_food_refund_does_not_restock(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    try:
        item = _item(client, owner_headers, stock=10)
        cust = _customer(client, owner_headers)
        sale = _confirm_food(client, owner_headers, cust["id"],
                             item["id"], 2)
        r = client.post(
            f"/api/v1/sales/{sale['id']}/refunds",
            json={"amount": sale["total"], "method": "CASH",
                  "reason": "cold food"},
            headers=owner_headers,
        )
        assert r.status_code == 201, r.text
        got = client.get(f"/api/v1/inventory/items/{item['id']}",
                         headers=owner_headers).json()
        assert got["stock_qty"] == 8  # eaten, not restocked
    finally:
        cur = client.get("/api/v1/shifts/current",
                         headers=owner_headers)
        if cur.status_code == 200:
            client.post(
                "/api/v1/shifts/current/close",
                json={"counted_cash": cur.json()["expected_live"]},
                headers=owner_headers,
            )


def test_reconcile_detects_stock_tamper(client, owner_headers):
    item = _item(client, owner_headers, stock=5)
    with get_connection() as conn:
        conn.execute("UPDATE inventory_items SET stock_qty = 999 "
                     "WHERE id = ?", (item["id"],))
    run = client.post("/api/v1/admin/reconcile",
                      headers=owner_headers).json()
    assert run["status"] == "ISSUES"
    assert any(i["check"] == "stock_ledger" for i in run["issues"])
    with get_connection() as conn:
        conn.execute("UPDATE inventory_items SET stock_qty = 5 "
                     "WHERE id = ?", (item["id"],))
    run2 = client.post("/api/v1/admin/reconcile",
                       headers=owner_headers).json()
    assert run2["status"] == "OK", run2["issues"]
