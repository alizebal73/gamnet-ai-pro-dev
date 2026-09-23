import uuid

from gamenet.server.db import get_connection
from gamenet.server.services.credit_service import CreditService


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


def _confirm_sale(client, headers, customer_id, items, **kw):
    body = {"customer_id": customer_id, "items": items}
    body.update(kw)
    sale = client.post("/api/v1/sales", json=body, headers=headers)
    assert sale.status_code == 201, sale.text
    sale = sale.json()
    pay = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": sale["total"]},
        headers=headers,
    )
    assert pay.status_code == 201, pay.text
    confirm = client.post(
        f"/api/v1/sales/{sale['id']}/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    return confirm.json()


def _package(client, headers, **kw):
    body = {"name": _uniq("PKG"), "duration_sec": 36000,
            "price": 500000, "bonus_sec": 3600, "validity_days": 30}
    body.update(kw)
    r = client.post("/api/v1/packages", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _plan(client, headers, **kw):
    body = {"name": _uniq("VIP"), "duration_days": 30,
            "price": 1500000, "discount_pct": 20}
    body.update(kw)
    r = client.post("/api/v1/vip-plans", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_time_sale_grants_credit(client, owner_headers):
    cust = _customer(client, owner_headers)
    assert (
        client.get(f"/api/v1/customers/{cust['id']}/credit",
                   headers=owner_headers).json()["total_remaining_sec"] == 0
    )
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "TIME", "duration_sec": 3600}])
    credit = client.get(
        f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
    ).json()
    assert credit["total_remaining_sec"] == 3600
    assert credit["entitlements"][0]["kind"] == "TIME_CREDIT"
    assert credit["entitlements"][0]["sale_id"] is not None


def test_draft_grants_nothing(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    assert sale["status"] == "DRAFT"
    credit = client.get(
        f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
    ).json()
    assert credit["total_remaining_sec"] == 0


def test_recharge_grants_balance(client, owner_headers):
    cust = _customer(client, owner_headers)
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "RECHARGE", "unit_price": 500000}])
    bal = client.get(
        f"/api/v1/customers/{cust['id']}/balance", headers=owner_headers
    ).json()
    assert bal["balance"] == 500000
    ledger = client.get(
        f"/api/v1/customers/{cust['id']}/balance-ledger",
        headers=owner_headers,
    ).json()
    assert ledger["items"][0]["kind"] == "RECHARGE"


def test_balance_payment_flow(client, owner_headers):
    cust = _customer(client, owner_headers)
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "RECHARGE", "unit_price": 100000}])
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    pay = client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "BALANCE", "amount": 80000},
        headers=owner_headers,
    )
    assert pay.status_code == 201, pay.text
    assert pay.json()["status"] == "PAID"
    assert (
        client.post(f"/api/v1/sales/{sale['id']}/confirm",
                    headers=owner_headers).status_code == 200
    )
    bal = client.get(
        f"/api/v1/customers/{cust['id']}/balance", headers=owner_headers
    ).json()["balance"]
    assert bal == 20000
    # Insufficient balance rejected:
    sale2 = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    poor = client.post(
        f"/api/v1/sales/{sale2['id']}/payments",
        json={"method": "BALANCE", "amount": 80000},
        headers=owner_headers,
    )
    assert poor.status_code == 409


def test_package_grants_credit_with_bonus_and_expiry(client, owner_headers):
    cust = _customer(client, owner_headers)
    pkg = _package(client, owner_headers)
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "PACKAGE", "ref_id": pkg["id"]}])
    credit = client.get(
        f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
    ).json()
    assert credit["total_remaining_sec"] == 39600
    ent = credit["entitlements"][0]
    assert ent["kind"] == "PACKAGE_CREDIT"
    assert ent["expires_at"] is not None


def test_vip_activation_and_renewal_queue(client, owner_headers):
    cust = _customer(client, owner_headers)
    plan = _plan(client, owner_headers)
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "VIP", "ref_id": plan["id"]}])
    credit = client.get(
        f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
    ).json()
    assert credit["active_vip"] is not None
    assert credit["active_vip"]["status"] == "ACTIVE"
    first_expiry = credit["active_vip"]["expires_at"]
    # Second purchase queues behind the first (AFTER_EXPIRY default):
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "VIP", "ref_id": plan["id"]}])
    credit = client.get(
        f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
    ).json()
    queued = [e for e in credit["entitlements"] if e["status"] == "PENDING"]
    assert len(queued) == 1
    assert queued[0]["starts_at"] == first_expiry


def test_vip_now_mode_supersedes(client, owner_headers):
    try:
        client.put("/api/v1/settings/vip_renewal_mode",
                   json={"value": "NOW"}, headers=owner_headers)
        cust = _customer(client, owner_headers)
        plan = _plan(client, owner_headers)
        _confirm_sale(client, owner_headers, cust["id"],
                      [{"kind": "VIP", "ref_id": plan["id"]}])
        _confirm_sale(client, owner_headers, cust["id"],
                      [{"kind": "VIP", "ref_id": plan["id"]}])
        credit = client.get(
            f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
        ).json()
        assert credit["active_vip"] is not None
        cancelled = [e for e in credit["entitlements"]
                     if e["status"] == "CANCELLED"]
        assert len(cancelled) == 1
    finally:
        client.put("/api/v1/settings/vip_renewal_mode",
                   json={"value": "AFTER_EXPIRY"}, headers=owner_headers)


def test_vip_expiry_derived_and_refresh(client, owner_headers):
    cust = _customer(client, owner_headers)
    plan = _plan(client, owner_headers)
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "VIP", "ref_id": plan["id"]}])
    # Backdate the VIP to the past (test-only SQL):
    with get_connection() as conn:
        conn.execute(
            "UPDATE entitlements SET expires_at = '2000-01-01T00:00:00Z' "
            "WHERE customer_id = ? AND kind = 'VIP'",
            (cust["id"],),
        )
    credit = client.get(
        f"/api/v1/customers/{cust['id']}/credit", headers=owner_headers
    ).json()
    assert credit["entitlements"][0]["effective_status"] == "EXPIRED"
    refreshed = client.post(
        f"/api/v1/customers/{cust['id']}/credit/refresh",
        headers=owner_headers,
    ).json()
    assert len(refreshed["expired"]) == 1


def test_consume_earliest_expiry_first(client, owner_headers):
    cust = _customer(client, owner_headers)
    soon = _package(client, owner_headers, duration_sec=3600,
                    bonus_sec=0, validity_days=1, price=10000)
    late = _package(client, owner_headers, duration_sec=3600,
                    bonus_sec=0, validity_days=30, price=10000)
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "PACKAGE", "ref_id": late["id"]}])
    _confirm_sale(client, owner_headers, cust["id"],
                  [{"kind": "PACKAGE", "ref_id": soon["id"]}])
    with get_connection() as conn:
        breakdown = CreditService(conn).consume(
            customer_id=cust["id"], seconds=1800,
            ref_type="test", ref_id="t1",
        )
    with get_connection() as conn:
        soon_row = next(
            e for e in CreditService(conn).credit_summary(cust["id"])["entitlements"]
            if e["ref_id"] == soon["id"]
        )
    assert breakdown[0]["entitlement_id"] == soon_row["id"]
    assert breakdown[0]["consumed_sec"] == 1800
    # Over-consume rejected:
    with get_connection() as conn:
        try:
            CreditService(conn).consume(
                customer_id=cust["id"], seconds=999999,
                ref_type="test", ref_id="t2",
            )
            raise AssertionError("expected InvalidState")
        except Exception as exc:
            assert "Insufficient" in str(exc)


def test_balance_adjust_permissions(client, owner_headers,
                                    make_user_with_token):
    cust = _customer(client, owner_headers)
    operator = make_user_with_token("operator")
    r = client.post(
        f"/api/v1/customers/{cust['id']}/balance-adjust",
        json={"amount": 50000, "reason": "promo"}, headers=operator,
    )
    assert r.status_code == 403  # no customer.edit_balance
    ok = client.post(
        f"/api/v1/customers/{cust['id']}/balance-adjust",
        json={"amount": 50000, "reason": "promo"}, headers=owner_headers,
    )
    assert ok.status_code == 201
    assert ok.json()["balance_after"] == 50000
    neg = client.post(
        f"/api/v1/customers/{cust['id']}/balance-adjust",
        json={"amount": -60000, "reason": "oops"}, headers=owner_headers,
    )
    assert neg.status_code == 409


def test_server_side_vip_package_pricing(client, owner_headers):
    cust = _customer(client, owner_headers)
    plan = _plan(client, owner_headers, price=1500000)
    # Client tries to cheat the price; server ignores it.
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"], "items": [
            {"kind": "VIP", "ref_id": plan["id"], "unit_price": 1}]},
        headers=owner_headers,
    )
    assert sale.status_code == 201
    assert sale.json()["total"] == 1500000


def test_inactive_catalog_rejected(client, owner_headers):
    cust = _customer(client, owner_headers)
    pkg = _package(client, owner_headers)
    off = client.patch(f"/api/v1/packages/{pkg['id']}",
                       json={"active": False}, headers=owner_headers)
    assert off.status_code == 200
    r = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "PACKAGE", "ref_id": pkg["id"]}]},
        headers=owner_headers,
    )
    assert r.status_code == 422


def test_catalog_permissions(client, make_user_with_token):
    operator = make_user_with_token("operator")
    assert client.get("/api/v1/packages", headers=operator).status_code == 200
    r = client.post("/api/v1/packages",
                    json={"name": _uniq("X"), "duration_sec": 60,
                          "price": 100},
                    headers=operator)
    assert r.status_code == 403


def test_cancel_refused_with_settled_payments(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": 1000}, headers=owner_headers,
    )
    r = client.post(f"/api/v1/sales/{sale['id']}/cancel",
                    json={"reason": "x"}, headers=owner_headers)
    assert r.status_code == 409
