import uuid

import pytest


@pytest.fixture(autouse=True)
def _close_open_shift(client, owner_headers):
    yield
    r = client.get("/api/v1/shifts/current", headers=owner_headers)
    if r.status_code == 200:
        live = r.json()["expected_live"]
        client.post(
            "/api/v1/shifts/current/close", json={"counted_cash": live},
            headers=owner_headers,
        )


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


def _cash_sale(client, headers, customer_id, seconds=3600):
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": customer_id,
              "items": [{"kind": "TIME", "duration_sec": seconds}]},
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": sale["total"]},
        headers=headers,
    )
    return client.post(f"/api/v1/sales/{sale['id']}/confirm",
                       headers=headers).json()


def test_open_and_current(client, owner_headers):
    opened = client.post("/api/v1/shifts/open", json={"opening_float": 50000},
                         headers=owner_headers)
    assert opened.status_code == 201, opened.text
    assert opened.json()["id"].startswith("SHF-")
    current = client.get("/api/v1/shifts/current",
                         headers=owner_headers).json()
    assert current["id"] == opened.json()["id"]
    assert current["expected_live"] == 50000
    assert current["status"] == "OPEN"


def test_double_open_rejected(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    again = client.post("/api/v1/shifts/open", json={},
                        headers=owner_headers)
    assert again.status_code == 409


def test_cash_sale_attaches_and_counts(client, owner_headers):
    shift = client.post("/api/v1/shifts/open",
                        json={"opening_float": 10000},
                        headers=owner_headers).json()
    cust = _customer(client, owner_headers)
    sale = _cash_sale(client, owner_headers, cust["id"])
    assert sale["shift_id"] == shift["id"]
    current = client.get("/api/v1/shifts/current",
                         headers=owner_headers).json()
    assert current["cash_paid"] == sale["total"]
    assert current["expected_live"] == 10000 + sale["total"]


def test_balance_payment_excluded_from_drawer(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    recharge = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "RECHARGE", "unit_price": 200000}]},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/v1/sales/{recharge['id']}/payments",
        json={"method": "CASH", "amount": recharge["total"]},
        headers=owner_headers,
    )
    client.post(f"/api/v1/sales/{recharge['id']}/confirm",
                headers=owner_headers)
    game = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/v1/sales/{game['id']}/payments",
        json={"method": "BALANCE", "amount": game["total"]},
        headers=owner_headers,
    )
    client.post(f"/api/v1/sales/{game['id']}/confirm",
                headers=owner_headers)
    current = client.get("/api/v1/shifts/current",
                         headers=owner_headers).json()
    assert current["cash_paid"] == recharge["total"]  # game paid by balance


def test_movements_affect_expected(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    client.post(
        "/api/v1/shifts/current/movements",
        json={"kind": "IN", "amount": 10000, "reason": "float top-up"},
        headers=owner_headers,
    )
    client.post(
        "/api/v1/shifts/current/movements",
        json={"kind": "OUT", "amount": 3000, "reason": "safe drop"},
        headers=owner_headers,
    )
    current = client.get("/api/v1/shifts/current",
                         headers=owner_headers).json()
    assert (current["moved_in"], current["moved_out"]) == (10000, 3000)
    assert current["expected_live"] == 7000
    bad = client.post(
        "/api/v1/shifts/current/movements",
        json={"kind": "SIDEWAYS", "amount": 1, "reason": "x"},
        headers=owner_headers,
    )
    assert bad.status_code == 400


def test_close_exact_balances(client, owner_headers):
    client.post("/api/v1/shifts/open", json={"opening_float": 5000},
                headers=owner_headers)
    cust = _customer(client, owner_headers)
    sale = _cash_sale(client, owner_headers, cust["id"])
    counted = 5000 + sale["total"]
    closed = client.post(
        "/api/v1/shifts/current/close", json={"counted_cash": counted},
        headers=owner_headers,
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["variance"] == 0
    assert closed.json()["expected_cash"] == counted
    assert client.get("/api/v1/shifts/current",
                      headers=owner_headers).status_code == 404


def test_close_variance_requires_note(client, owner_headers):
    client.post("/api/v1/shifts/open", json={"opening_float": 10000},
                headers=owner_headers)
    short = client.post("/api/v1/shifts/current/close",
                        json={"counted_cash": 9500},
                        headers=owner_headers)
    assert short.status_code == 400
    closed = client.post(
        "/api/v1/shifts/current/close",
        json={"counted_cash": 9500, "note": "500 short, checking camera"},
        headers=owner_headers,
    )
    assert closed.json()["variance"] == -500
    assert "camera" in closed.json()["note"]


def test_close_and_movement_without_shift_404(client, owner_headers):
    assert client.get("/api/v1/shifts/current",
                      headers=owner_headers).status_code == 404
    assert client.post(
        "/api/v1/shifts/current/close", json={"counted_cash": 0},
        headers=owner_headers).status_code == 404
    assert client.post(
        "/api/v1/shifts/current/movements",
        json={"kind": "IN", "amount": 1, "reason": "x"},
        headers=owner_headers).status_code == 404


def test_shift_permissions(client, owner_headers, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert client.post("/api/v1/shifts/open", json={},
                       headers=viewer).status_code == 403
    operator = make_user_with_token("operator")
    opened = client.post("/api/v1/shifts/open", json={"opening_float": 7},
                         headers=operator)
    assert opened.status_code == 201
    assert client.get("/api/v1/shifts/current",
                      headers=viewer).status_code == 403


def test_history_and_detail(client, owner_headers):
    opened = client.post("/api/v1/shifts/open", json={},
                         headers=owner_headers).json()
    client.post("/api/v1/shifts/current/close", json={"counted_cash": 0},
                headers=owner_headers)
    history = client.get("/api/v1/shifts",
                         headers=owner_headers).json()
    assert opened["id"] in [s["id"] for s in history]
    detail = client.get(f"/api/v1/shifts/{opened['id']}",
                        headers=owner_headers).json()
    assert detail["status"] == "CLOSED"
    assert detail["variance"] == 0
    assert client.get("/api/v1/shifts/SHF-NOPE",
                      headers=owner_headers).status_code == 404
