import uuid

from gamenet.operator_app.cli import CliError, main
from gamenet.server.db import get_connection


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _customer(client, headers, pin="1234"):
    r = client.post(
        "/api/v1/customers",
        json={"name": _uniq("Cust"), "pin": pin},
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


def _grant(client, headers, customer_id, seconds=3600):
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
    client.post(f"/api/v1/sales/{sale['id']}/confirm", headers=headers)


def _active_session(client, headers, customer_id, pc_id):
    s = client.post(
        "/api/v1/sessions",
        json={"customer_id": customer_id, "pc_id": pc_id},
        headers=headers,
    ).json()
    client.post(f"/api/v1/sessions/{s['id']}/authorize", json={},
                headers=headers)
    client.post(f"/api/v1/sessions/{s['id']}/start", headers=headers)
    return s["id"]


# ---------- customer login ----------

def test_customer_login_me_logout(client, owner_headers):
    cust = _customer(client, owner_headers)
    r = client.post(
        "/api/v1/customers/login",
        json={"identifier": str(cust["customer_number"]), "pin": "1234"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer"]["id"] == cust["id"]
    assert "pin" not in str(body["customer"]).lower()
    token = body["token"]
    me = client.get("/api/v1/customers/me",
                    headers={"Authorization": f"Bearer {token}"}).json()
    assert me["customer"]["id"] == cust["id"]
    assert me["balance"] == 0
    assert me["remaining_sec"] == 0
    out = client.post("/api/v1/customers/logout",
                      headers={"Authorization": f"Bearer {token}"})
    assert out.json() == {"ok": True}
    gone = client.get("/api/v1/customers/me",
                      headers={"Authorization": f"Bearer {token}"})
    assert gone.status_code == 401


def test_login_by_id_and_wrong_pin(client, owner_headers):
    cust = _customer(client, owner_headers, pin="9999")
    ok = client.post("/api/v1/customers/login",
                     json={"identifier": cust["id"], "pin": "9999"})
    assert ok.status_code == 200
    bad = client.post("/api/v1/customers/login",
                      json={"identifier": cust["id"], "pin": "0000"})
    assert bad.status_code == 401
    unknown = client.post(
        "/api/v1/customers/login",
        json={"identifier": "CUS-NOPE", "pin": "1234"})
    assert unknown.status_code == 401
    assert client.get("/api/v1/customers/me").status_code == 401


def test_customer_lockout_and_recovery(client, owner_headers):
    cust = _customer(client, owner_headers, pin="4321")
    client.put("/api/v1/settings/customer_max_attempts",
               json={"value": "3"}, headers=owner_headers)
    try:
        assert client.post(
            "/api/v1/customers/login",
            json={"identifier": cust["id"], "pin": "bad1"},
        ).status_code == 401
        assert client.post(
            "/api/v1/customers/login",
            json={"identifier": cust["id"], "pin": "bad2"},
        ).status_code == 401
        locked = client.post(
            "/api/v1/customers/login",
            json={"identifier": cust["id"], "pin": "bad3"})
        assert locked.status_code == 423
        assert locked.json()["detail"]["locked_until"] is not None
        # Correct PIN still locked:
        assert client.post(
            "/api/v1/customers/login",
            json={"identifier": cust["id"], "pin": "4321"},
        ).status_code == 423
        # After the lock expires, the correct PIN works again:
        with get_connection() as conn:
            conn.execute(
                "UPDATE customer_auth SET locked_until = "
                "'2000-01-01T00:00:00Z' WHERE customer_id = ?",
                (cust["id"],),
            )
        ok = client.post("/api/v1/customers/login",
                         json={"identifier": cust["id"], "pin": "4321"})
        assert ok.status_code == 200, ok.text
    finally:
        client.put("/api/v1/settings/customer_max_attempts",
                   json={"value": "5"}, headers=owner_headers)


# ---------- session extend ----------

def test_extend_active_session(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    before = client.get("/api/v1/customers/me", headers=owner_headers)
    del before
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    before_detail = client.get(f"/api/v1/sessions/{sid}",
                               headers=owner_headers).json()
    extended = client.post(f"/api/v1/sessions/{sid}/extend",
                           params={"note": "paid for 1 more hour"},
                           headers=owner_headers)
    assert extended.status_code == 200, extended.text
    body = extended.json()
    kinds = [e["kind"] for e in body["events"]]
    assert "EXTENDED" in kinds
    assert len(body["events"]) == len(before_detail["events"]) + 1
    assert body["status"] == "ACTIVE"
    assert body["expected_remaining_sec"] == body[
        "customer_remaining_sec"]
    assert body["expected_ends_at"] is not None


def test_extend_without_credit_or_terminal(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    s = client.post(
        "/api/v1/sessions",
        json={"customer_id": cust["id"], "pc_id": pc["id"]},
        headers=owner_headers,
    ).json()
    # PENDING is not extendable:
    assert client.post(f"/api/v1/sessions/{s['id']}/extend",
                       headers=owner_headers).status_code == 409
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"],
                          _pc(client, owner_headers)["id"])
    client.post(f"/api/v1/sessions/{sid}/end", json={},
                headers=owner_headers)
    assert client.post(f"/api/v1/sessions/{sid}/extend",
                       headers=owner_headers).status_code == 409


# ---------- quick flows ----------

def test_quick_customer_with_recharge(client, owner_headers):
    r = client.post(
        "/api/v1/quick/customer",
        json={"name": _uniq("QC"), "pin": "1234",
              "recharge_amount": 500000},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["customer"]["id"].startswith("CUST-")
    assert body["sale"]["status"] == "CONFIRMED"
    assert body["sale"]["total"] == 500000
    bal = client.get(
        f"/api/v1/customers/{body['customer']['id']}/balance",
        headers=owner_headers).json()
    assert bal["balance"] == 500000


def test_quick_customer_without_recharge(client, owner_headers):
    r = client.post(
        "/api/v1/quick/customer",
        json={"name": _uniq("QC"), "pin": "1234"},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["sale"] is None


def test_quick_sale_confirms_and_is_atomic(client, owner_headers):
    cust = _customer(client, owner_headers)
    # Learn the priced total with a throwaway draft:
    draft = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}]},
        headers=owner_headers,
    ).json()
    total = draft["total"]
    with get_connection() as conn:
        before = conn.execute(
            "SELECT COUNT(*) AS n FROM sales WHERE customer_id = ?",
            (cust["id"],),
        ).fetchone()["n"]
    # Underpay: must fail AND leave no draft behind.
    short = client.post(
        "/api/v1/quick/sale",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}],
              "payments": [{"method": "CASH", "amount": total - 1}]},
        headers=owner_headers,
    )
    assert short.status_code == 409
    with get_connection() as conn:
        after = conn.execute(
            "SELECT COUNT(*) AS n FROM sales WHERE customer_id = ?",
            (cust["id"],),
        ).fetchone()["n"]
    assert after == before
    # Full pay: one call to CONFIRMED.
    done = client.post(
        "/api/v1/quick/sale",
        json={"customer_id": cust["id"],
              "items": [{"kind": "TIME", "duration_sec": 3600}],
              "payments": [{"method": "CASH", "amount": total}]},
        headers=owner_headers,
    )
    assert done.status_code == 201, done.text
    assert done.json()["status"] == "CONFIRMED"


def test_quick_sale_idempotent(client, owner_headers):
    cust = _customer(client, owner_headers)
    draft = client.post(
        "/api/v1/sales",
        json={"customer_id": cust["id"],
              "items": [{"kind": "RECHARGE", "unit_price": 100000}]},
        headers=owner_headers,
    ).json()
    body = {"customer_id": cust["id"],
            "items": [{"kind": "RECHARGE", "unit_price": 100000}],
            "payments": [{"method": "CASH",
                          "amount": draft["total"]}]}
    headers = dict(owner_headers)
    headers["X-Request-ID"] = f"quick-{uuid.uuid4().hex}"
    first = client.post("/api/v1/quick/sale", json=body, headers=headers)
    second = client.post("/api/v1/quick/sale", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert second.json()["id"] == first.json()["id"]
    with get_connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM sales WHERE customer_id = ? "
            "AND status = 'CONFIRMED'",
            (cust["id"],),
        ).fetchone()["n"]
    assert n == 1


# ---------- operator shell ----------

def test_cli_quick_sale_builds_request():
    seen = {}

    def fake(method, path, body=None):
        seen.update(method=method, path=path, body=body)
        return {"id": "SAL-1"}

    rc = main(
        ["--token", "t", "quick-sale", "--customer", "CUS-1",
         "--item", '{"kind":"TIME","duration_sec":60}',
         "--pay", "CASH:100"],
        call=fake,
    )
    assert rc == 0
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/quick/sale"
    assert seen["body"]["payments"] == [{"method": "CASH",
                                         "amount": 100}]


def test_cli_login_and_error_path(capsys):
    def fake(method, path, body=None):
        assert body == {"username": "u", "password": "p"}
        return {"token": "tok"}

    assert main(["login", "--username", "u", "--password", "p"],
                call=fake) == 0
    assert "tok" in capsys.readouterr().out

    def boom(method, path, body=None):
        raise CliError("HTTP 401: nope", status=401)

    assert main(["--token", "bad", "queue"], call=boom) == 1
    assert "error" in capsys.readouterr().err


def test_cli_quick_customer_args():
    seen = {}

    def fake(method, path, body=None):
        seen.update(body=body)
        return {"customer": {}}

    rc = main(
        ["--token", "t", "quick-customer", "--name", "N",
         "--pin", "1234", "--recharge", "5000"],
        call=fake,
    )
    assert rc == 0
    assert seen["body"]["recharge_amount"] == 5000


def test_quickwins_permissions(client, owner_headers,
                               make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert client.post("/api/v1/quick/customer", json={},
                       headers=viewer).status_code == 403
    assert client.post("/api/v1/quick/sale", json={},
                       headers=viewer).status_code == 403
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    assert client.post(f"/api/v1/sessions/{sid}/extend",
                       headers=viewer).status_code == 403
