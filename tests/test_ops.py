import uuid

from gamenet.server.db import get_connection
from gamenet.server.workers.recovery import startup_checks


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


def test_audit_chain_verifies(client, owner_headers):
    _customer(client, owner_headers)
    v = client.get("/api/v1/admin/audit-verify",
                   headers=owner_headers).json()
    assert v["ok"] is True
    assert v["checked"] >= 1


def test_audit_tamper_detected(client, owner_headers):
    cust = _customer(client, owner_headers)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM audit_logs WHERE customer_id = ? AND hash IS NOT NULL LIMIT 1",
            (cust["id"],),
        ).fetchone()
        assert row is not None
        conn.execute(
            "UPDATE audit_logs SET new_value = 'TAMPERED' WHERE id = ?",
            (row["id"],),
        )
    v = client.get("/api/v1/admin/audit-verify",
                   headers=owner_headers).json()
    assert v["ok"] is False
    assert v["broken_id"] == row["id"]


def test_safe_mode_blocks_mutations(client, owner_headers):
    try:
        on = client.post("/api/v1/admin/safe-mode",
                         json={"enabled": True, "reason": "drill"},
                         headers=owner_headers)
        assert on.status_code == 200
        # Reads still work:
        assert (
            client.get("/api/v1/customers/search", params={"q": "x"},
                       headers=owner_headers).status_code == 200
        )
        # Mutations blocked:
        r = client.post("/api/v1/customers",
                        json={"name": "Blocked", "pin": "1234"},
                        headers=owner_headers)
        assert r.status_code == 503
        r = client.post("/api/v1/sales",
                        json={"customer_id": "x", "items": []},
                        headers=owner_headers)
        assert r.status_code == 503
    finally:
        off = client.post("/api/v1/admin/safe-mode",
                          json={"enabled": False},
                          headers=owner_headers)
        assert off.status_code == 200
    r = client.post("/api/v1/customers",
                    json={"name": _uniq("After"), "pin": "1234"},
                    headers=owner_headers)
    assert r.status_code == 201


def test_reconcile_clean_then_broken_sale(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    ok = client.post("/api/v1/reconcile-nope", headers=owner_headers)
    assert ok.status_code in (404, 405)  # sanity: wrong path fails
    run1 = client.post("/api/v1/admin/reconcile",
                       headers=owner_headers).json()
    assert run1["status"] == "OK", run1["issues"]
    # Break the sale total directly in SQL:
    with get_connection() as conn:
        conn.execute("UPDATE sales SET total = 1 WHERE id = ?",
                     (sale["id"],))
    run2 = client.post("/api/v1/admin/reconcile",
                       headers=owner_headers).json()
    assert run2["status"] == "ISSUES"
    assert any(i["check"] == "sale_total" for i in run2["issues"])
    # Restore so later runs stay meaningful:
    with get_connection() as conn:
        conn.execute("UPDATE sales SET total = 80000 WHERE id = ?",
                     (sale["id"],))
    run3 = client.post("/api/v1/admin/reconcile",
                       headers=owner_headers).json()
    assert run3["status"] == "OK", run3["issues"]
    latest = client.get("/api/v1/admin/reconcile/latest",
                        headers=owner_headers).json()
    assert latest["id"] == run3["id"]


def test_reconcile_detects_missing_grant(client, owner_headers):
    cust = _customer(client, owner_headers)
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/v1/sales/{sale['id']}/payments",
        json={"method": "CASH", "amount": sale["total"]},
        headers=owner_headers,
    )
    client.post(f"/api/v1/sales/{sale['id']}/confirm",
                headers=owner_headers)
    # Remove the granted entitlement + ledger (simulating a partial failure):
    with get_connection() as conn:
        ent = conn.execute(
            "SELECT id FROM entitlements WHERE sale_id = ?", (sale["id"],)
        ).fetchone()
        conn.execute("DELETE FROM entitlement_ledger WHERE entitlement_id = ?",
                     (ent["id"],))
        conn.execute("DELETE FROM entitlements WHERE id = ?", (ent["id"],))
    run = client.post("/api/v1/admin/reconcile",
                      headers=owner_headers).json()
    assert run["status"] == "ISSUES"
    assert any(i["check"] == "activation_missing" for i in run["issues"])


def test_audit_read_permissions(client, make_user_with_token):
    operator = make_user_with_token("operator")
    assert (
        client.get("/api/v1/admin/audit",
                   headers=operator).status_code == 403
    )
    assert (
        client.post("/api/v1/admin/safe-mode",
                    json={"enabled": True}, headers=operator).status_code == 403
    )


def test_startup_checks_healthy():
    report = startup_checks()
    assert report["integrity_ok"] is True
    assert report["safe_mode"] is False
