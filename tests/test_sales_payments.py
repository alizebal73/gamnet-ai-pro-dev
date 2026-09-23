import uuid


def _rid() -> str:
    return f"req-{uuid.uuid4().hex}"


def _customer(client, headers, name=None):
    name = name or f"Cust {uuid.uuid4().hex[:6]}"
    r = client.post(
        "/api/v1/customers", json={"name": name, "pin": "1234"}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def _draft(client, headers, customer_id, **overrides):
    body = {
        "customer_id": customer_id,
        "items": [{"kind": "TIME", "duration_sec": 3600}],
    }
    body.update(overrides)
    r = client.post("/api/v1/sales", json=body, headers=headers)
    return r


def test_create_time_sale_defaults(client, owner_headers):
    cust = _customer(client, owner_headers)
    r = _draft(client, owner_headers, cust["id"])
    assert r.status_code == 201, r.text
    sale = r.json()
    assert sale["id"].startswith("SALE-")
    assert sale["status"] == "DRAFT"
    assert sale["subtotal"] == 80000
    assert sale["total"] == 80000
    assert sale["items"][0]["price_snapshot"]["total"] == 80000


def test_unknown_customer_404(client, owner_headers):
    r = _draft(client, owner_headers, "CUST-NOPE")
    assert r.status_code == 404


def test_unsupported_kind_422(client, owner_headers):
    cust = _customer(client, owner_headers)
    r = _draft(client, owner_headers, cust["id"],
               items=[{"kind": "VIP", "unit_price": 100}])
    assert r.status_code == 422


def test_discount_rules(client, owner_headers, make_user_with_token):
    cust = _customer(client, owner_headers)
    # Owner: unlimited with reason.
    r = _draft(client, owner_headers, cust["id"],
               discount_pct=50, discount_reason="campaign")
    assert r.status_code == 201
    assert r.json()["total"] == 40000
    # Discount without reason rejected.
    r = _draft(client, owner_headers, cust["id"], discount_pct=10)
    assert r.status_code == 422
    # Operator over the 10% limit rejected.
    operator = make_user_with_token("operator")
    cust2 = _customer(client, owner_headers)
    r = _draft(client, operator, cust2["id"],
               discount_pct=20, discount_reason="x")
    assert r.status_code == 403
    r = _draft(client, operator, cust2["id"],
               discount_pct=10, discount_reason="ok")
    assert r.status_code == 201
    assert r.json()["total"] == 72000


def test_cash_confirm_flow(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    pay = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 80000, "tendered": 100000},
        headers=owner_headers,
    )
    assert pay.status_code == 201
    assert pay.json()["status"] == "PAID"
    assert pay.json()["id"].startswith("PAY-")
    confirm = client.post(
        f"/api/v1/sales/{sale['id']}/confirm", headers=owner_headers
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "CONFIRMED"
    # Confirm is naturally idempotent:
    again = client.post(
        f"/api/v1/sales/{sale['id']}/confirm", headers=owner_headers
    )
    assert again.status_code == 200
    assert again.json()["status"] == "CONFIRMED"


def test_mixed_and_under_over_payments(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    p1 = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 30000},
        headers=owner_headers,
    )
    assert p1.status_code == 201
    # Overpay rejected:
    over = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 60000},
        headers=owner_headers,
    )
    assert over.status_code == 422
    # Underpaid confirm rejected:
    short = client.post(
        f"/api/v1/sales/{sale['id']}/confirm", headers=owner_headers
    )
    assert short.status_code == 409
    # Mixed: card (manual with ref) covers the rest:
    p2 = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CARD", "amount": 50000, "provider_ref": "POS-1"},
        headers=owner_headers,
    )
    assert p2.status_code == 201
    assert p2.json()["status"] == "PAID"
    confirm = client.post(
        f"/api/v1/sales/{sale['id']}/confirm", headers=owner_headers
    )
    assert confirm.status_code == 200


def test_manual_card_needs_reference(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CARD", "amount": 80000},
        headers=owner_headers,
    )
    assert r.status_code == 422


def test_cash_tendered_validated(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 80000, "tendered": 100},
        headers=owner_headers,
    )
    assert r.status_code == 422


def test_balance_rejected_until_ledger(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "BALANCE", "amount": 100},
        headers=owner_headers,
    )
    assert r.status_code == 422


def test_mock_card_auto_paid(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CARD", "amount": 80000, "provider": "mock"},
        headers=owner_headers,
    )
    assert r.status_code == 201
    assert r.json()["status"] == "PAID"
    assert r.json()["provider_ref"].startswith("MOCK-")


def test_unknown_then_reconcile_to_paid(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CARD", "amount": 80000, "provider": "mock",
              "meta": {"simulate": "timeout-then-paid"}},
        headers=owner_headers,
    )
    assert r.json()["status"] == "UNKNOWN"
    pay_id = r.json()["id"]
    # Sale cannot confirm while payment is UNKNOWN:
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/confirm",
                    headers=owner_headers).status_code == 409
    )
    # UNKNOWN queue lists it:
    queue = client.get(
        "/api/v1/payments/unknown-queue", headers=owner_headers
    ).json()
    assert any(p["id"] == pay_id for p in queue["items"])
    # Inquiry resolves to PAID (no double charge: same payment row):
    rec = client.post(
        f"/api/v1/payments/{pay_id}/reconcile", headers=owner_headers
    )
    assert rec.status_code == 200
    assert rec.json()["status"] == "PAID"
    assert rec.json()["id"] == pay_id
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/confirm",
                    headers=owner_headers).status_code == 200
    )


def test_unknown_then_reconcile_to_failed(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    r = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 1000},
        headers=owner_headers,
    )
    assert r.status_code == 201
    u = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CARD", "amount": 79000, "provider": "mock",
              "meta": {"simulate": "timeout-then-failed"}},
        headers=owner_headers,
    )
    assert u.json()["status"] == "UNKNOWN"
    rec = client.post(
        f"/api/v1/payments/{u.json()['id']}/reconcile", headers=owner_headers
    )
    assert rec.json()["status"] == "FAILED"
    # Replacement cash payment covers the rest:
    fix = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 79000},
        headers=owner_headers,
    )
    assert fix.status_code == 201
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/confirm",
                    headers=owner_headers).status_code == 200
    )


def test_cancel_draft(client, owner_headers, make_user_with_token):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    # Operator lacks sales.cancel:
    operator = make_user_with_token("operator")
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/cancel",
                    json={"reason": "x"}, headers=operator).status_code == 403
    )
    # Reason required:
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/cancel",
                    json={"reason": ""}, headers=owner_headers).status_code == 422
    )
    cancelled = client.post(
        f"/api/v1/sales/{sale['id']}/cancel",
        json={"reason": "customer left"}, headers=owner_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/confirm",
                    headers=owner_headers).status_code == 409
    )


def test_sale_permissions(client, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert (
        client.post("/api/v1/sales", json={"customer_id": "x", "items": []},
                    headers=viewer).status_code == 403
    )


def test_idempotent_sale_create(client, owner_headers):
    cust = _customer(client, owner_headers)
    headers = {**owner_headers, "X-Request-ID": _rid()}
    body = {"customer_id": cust["id"],
            "items": [{"kind": "TIME", "duration_sec": 1800}]}
    first = client.post("/api/v1/sales", json=body, headers=headers)
    second = client.post("/api/v1/sales", json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_get_and_list_sales(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _draft(client, owner_headers, cust["id"]).json()
    got = client.get(f"/api/v1/sales/{sale['id']}", headers=owner_headers)
    assert got.status_code == 200
    assert got.json()["id"] == sale["id"]
    listed = client.get(
        "/api/v1/sales", params={"customer_id": cust["id"]},
        headers=owner_headers,
    ).json()
    assert any(s["id"] == sale["id"] for s in listed["items"])
