import uuid
from datetime import UTC, datetime, timedelta

import pytest

from gamenet.server.db import get_connection, to_utc_iso


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


def _confirm_sale(client, headers, customer_id, items, method="CASH"):
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": customer_id, "items": items},
        headers=headers,
    ).json()
    assert "id" in sale, sale
    pay = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": method, "amount": sale["total"]},
        headers=headers,
    )
    assert pay.status_code == 201, pay.text
    done = client.post(f"/api/v1/sales/{sale['id']}/confirm",
                       headers=headers)
    assert done.status_code == 200, done.text
    return done.json()


def _credit(client, headers, customer_id):
    return client.get(f"/api/v1/customers/{customer_id}/credit",
                      headers=headers).json()


def _balance(client, headers, customer_id):
    return client.get(f"/api/v1/customers/{customer_id}/balance",
                      headers=headers).json()["balance"]


def _plan(client, headers):
    r = client.post(
        "/api/v1/vip-plans",
        json={"name": _uniq("VIP"), "duration_days": 30,
              "price": 1500000, "discount_pct": 0},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _refund(client, headers, sale_id, amount, method="CASH",
            reason="customer asked"):
    return client.post(
        f"/api/v1/sales/{sale_id}/refunds",
        json={"amount": amount, "method": method, "reason": reason},
        headers=headers,
    )


def test_full_cash_refund_revokes_credit(client, owner_headers):
    client.post("/api/v1/shifts/open", json={"opening_float": 10000},
                headers=owner_headers)
    cust = _customer(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "TIME", "duration_sec": 3600}])
    assert _credit(client, owner_headers, cust["id"])[
        "total_remaining_sec"] == 3600
    r = _refund(client, owner_headers, sale["id"], sale["total"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["refund"]["id"].startswith("RFD-")
    assert body["revoked_sec"] == 3600
    assert body["refunded_total"] == sale["total"]
    assert _credit(client, owner_headers, cust["id"])[
        "total_remaining_sec"] == 0
    detail = client.get(f"/api/v1/sales/{sale['id']}",
                        headers=owner_headers).json()
    assert detail["refunded_total"] == sale["total"]
    assert len(detail["refunds"]) == 1
    current = client.get("/api/v1/shifts/current",
                         headers=owner_headers).json()
    assert current["expected_live"] == 10000  # cash in, refund out


def test_partial_refund_proportional_then_rest(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "TIME", "duration_sec": 3600}])
    half = sale["total"] // 2
    first = _refund(client, owner_headers, sale["id"], half)
    assert first.status_code == 201
    assert first.json()["revoked_sec"] == 1800
    assert _credit(client, owner_headers, cust["id"])[
        "total_remaining_sec"] == 1800
    over = _refund(client, owner_headers, sale["id"], sale["total"])
    assert over.status_code == 409
    rest = _refund(client, owner_headers, sale["id"],
                   sale["total"] - half)
    assert rest.json()["refunded_total"] == sale["total"]
    assert _credit(client, owner_headers, cust["id"])[
        "total_remaining_sec"] == 0


def test_consumed_seconds_never_clawed_back(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    pc = client.post(
        "/api/v1/pcs",
        json={"device_code": _uniq("PC"), "display_name": "T"},
        headers=owner_headers,
    ).json()
    sale = _confirm_sale(client, owner_headers, cust["id"],
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
    past = to_utc_iso(datetime.now(UTC) - timedelta(seconds=1200))
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET last_accounted_at = ? WHERE id = ?",
            (past, s["id"]),
        )
    client.post(f"/api/v1/sessions/{s['id']}/pause", json={},
                headers=owner_headers)
    assert _credit(client, owner_headers, cust["id"])[
        "total_remaining_sec"] == 2400
    r = _refund(client, owner_headers, sale["id"], sale["total"])
    assert r.json()["revoked_sec"] == 2400  # remaining only
    detail = client.get(f"/api/v1/sessions/{s['id']}",
                        headers=owner_headers).json()
    assert detail["total_consumed_sec"] == 1200  # history intact


def test_cash_refund_needs_shift_balance_does_not(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "TIME", "duration_sec": 3600}])
    assert _refund(client, owner_headers, sale["id"],
                   sale["total"]).status_code == 409
    r = _refund(client, owner_headers, sale["id"], sale["total"],
                method="BALANCE")
    assert r.status_code == 201, r.text
    assert r.json()["refund"]["shift_id"] is None
    assert _balance(client, owner_headers, cust["id"]) == sale["total"]


def test_recharge_refund_claws_balance(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "RECHARGE", "unit_price": 200000}])
    assert _balance(client, owner_headers, cust["id"]) == 200000
    r = _refund(client, owner_headers, sale["id"], sale["total"])
    assert r.status_code == 201
    assert r.json()["clawed_balance"] == 200000
    assert _balance(client, owner_headers, cust["id"]) == 0


def test_recharge_refund_blocked_after_spend(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    topup = _confirm_sale(client, owner_headers, cust["id"],
                          [{"kind": "RECHARGE", "unit_price": 200000}])
    game = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 1800}]},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/v1/sales/{game['id']}/payments",
        json={"method": "BALANCE", "amount": game["total"]},
        headers=owner_headers,
    )
    client.post(f"/api/v1/sales/{game['id']}/confirm",
                headers=owner_headers)
    left = _balance(client, owner_headers, cust["id"])
    assert 0 < left < 200000
    r = _refund(client, owner_headers, topup["id"], topup["total"])
    assert r.status_code == 409
    assert _balance(client, owner_headers, cust["id"]) == left


def test_vip_full_refund_cancels_with_chain_promotion(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    plan = _plan(client, owner_headers)
    first = _confirm_sale(client, owner_headers, cust["id"],
                          [{"kind": "VIP", "ref_id": plan["id"]}])
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "VIP", "ref_id": plan["id"]}])
    assert _credit(client, owner_headers, cust["id"])[
        "active_vip"]["status"] == "ACTIVE"
    r = _refund(client, owner_headers, first["id"], first["total"])
    assert r.status_code == 201
    assert len(r.json()["vips_cancelled"]) == 1
    credit = _credit(client, owner_headers, cust["id"])
    # The queued VIP starts in the future, so nothing is promoted yet —
    # but the cancelled one is gone and the queue survives.
    assert credit["active_vip"] is None
    queued = [e for e in credit["entitlements"]
              if e["status"] == "PENDING"]
    assert len(queued) == 1
    cancelled = [e for e in credit["entitlements"]
                 if e["status"] == "CANCELLED"]
    assert [e["id"] for e in cancelled] == r.json()["vips_cancelled"]


def test_vip_partial_refund_keeps_vip(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    plan = _plan(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "VIP", "ref_id": plan["id"]}])
    r = _refund(client, owner_headers, sale["id"], sale["total"] // 2)
    assert r.status_code == 201
    assert r.json()["vips_cancelled"] == []
    assert _credit(client, owner_headers, cust["id"])[
        "active_vip"]["status"] == "ACTIVE"


def test_draft_and_cancelled_rejected(client, owner_headers):
    cust = _customer(client, owner_headers)
    draft = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    assert _refund(client, owner_headers, draft["id"], 1).status_code == 409
    client.post(f"/api/v1/sales/{draft['id']}/cancel",
                json={"reason": "changed mind"}, headers=owner_headers)
    assert _refund(client, owner_headers, draft["id"], 1).status_code == 409
    assert _refund(client, owner_headers, "SALE-NOPE", 1).status_code == 404


def test_refund_permissions(client, owner_headers, make_user_with_token):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "TIME", "duration_sec": 3600}])
    operator = make_user_with_token("operator")
    assert _refund(client, operator, sale["id"],
                   sale["total"]).status_code == 403
    manager = make_user_with_token("manager")
    r = _refund(client, manager, sale["id"], sale["total"])
    assert r.status_code == 201, r.text


def test_refund_listed_and_audited(client, owner_headers):
    client.post("/api/v1/shifts/open", json={}, headers=owner_headers)
    cust = _customer(client, owner_headers)
    sale = _confirm_sale(client, owner_headers, cust["id"],
                         [{"kind": "TIME", "duration_sec": 3600}])
    _refund(client, owner_headers, sale["id"], 1000, reason="goodwill")
    listed = client.get(f"/api/v1/sales/{sale['id']}/refunds",
                        headers=owner_headers).json()
    assert len(listed) == 1
    assert listed[0]["reason"] == "goodwill"
    audit = client.get("/api/v1/admin/audit", params={"action": "SALE_REFUND"},
                       headers=owner_headers).json()
    assert any(i["entity_id"] == listed[0]["id"] for i in audit["items"])
