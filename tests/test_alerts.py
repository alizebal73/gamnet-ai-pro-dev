import uuid

from gamenet.server.db import get_connection
from gamenet.server.services import telegram_service


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _pc(client, headers):
    code = _uniq("PC")
    return client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=headers,
    ).json()


def _set(client, headers, key, value):
    r = client.put(f"/api/v1/settings/{key}", json={"value": value},
                   headers=headers)
    assert r.status_code == 200, r.text


def _alerts(client, headers, status=None):
    params = {"status": status} if status else {}
    return client.get("/api/v1/alerts", params=params,
                      headers=headers).json()


def _evaluate(client, headers):
    r = client.post("/api/v1/alerts/evaluate", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _resolve_all(client, headers, source=None):
    for alert in _alerts(client, headers)["items"]:
        if alert["status"] in ("OPEN", "ACKED") and (
                source is None or alert["source"] == source):
            client.post(f"/api/v1/alerts/{alert['id']}/resolve",
                        headers=headers)


def test_disk_alert_and_auto_resolve(client, owner_headers):
    _set(client, owner_headers, "alert_disk_min_mb", "1000000")
    try:
        result = _evaluate(client, owner_headers)
        disks = [a for a in result["created"]
                 if a["source"] == "SERVER_DISK"]
        assert len(disks) == 1
        assert disks[0]["severity"] == "CRITICAL"
        assert disks[0]["id"].startswith("ALR-")
        # Second run dedupes (no duplicate OPEN alert):
        again = _evaluate(client, owner_headers)
        assert [a for a in again["created"]
                if a["source"] == "SERVER_DISK"] == []
        assert _alerts(client, owner_headers, "OPEN")["total"] >= 1
    finally:
        _set(client, owner_headers, "alert_disk_min_mb", "2048")
    result = _evaluate(client, owner_headers)
    assert disks[0]["id"] in result["resolved"]
    got = client.get(f"/api/v1/alerts/{disks[0]['id']}",
                     headers=owner_headers).json()
    assert got["status"] == "RESOLVED"


def test_pc_offline_alert_lifecycle(client, owner_headers):
    pc = _pc(client, owner_headers)
    with get_connection() as conn:
        conn.execute(
            "UPDATE pcs SET last_seen_at = '2000-01-01T00:00:00Z' "
            "WHERE id = ?",
            (pc["id"],),
        )
    try:
        result = _evaluate(client, owner_headers)
        mine = [a for a in result["created"]
                if a["entity_id"] == pc["id"]]
        assert len(mine) == 1
        assert mine[0]["source"] == "PC_OFFLINE"
        # PC comes back: alert auto-resolves.
        with get_connection() as conn:
            conn.execute(
                "UPDATE pcs SET last_seen_at = '2999-01-01T00:00:00Z' "
                "WHERE id = ?",
                (pc["id"],),
            )
        result = _evaluate(client, owner_headers)
        assert mine[0]["id"] in result["resolved"]
    finally:
        with get_connection() as conn:
            conn.execute(
                "UPDATE pcs SET last_seen_at = '2999-01-01T00:00:00Z' "
                "WHERE id = ?",
                (pc["id"],),
            )
        _resolve_all(client, owner_headers, "PC_OFFLINE")


def test_shift_stuck_alert(client, owner_headers):
    opened = client.post("/api/v1/shifts/open",
                         json={"opening_float": 0},
                         headers=owner_headers)
    assert opened.status_code in (201, 409), opened.text
    if opened.status_code == 201:
        shift_id = opened.json()["id"]
    else:
        shift_id = client.get("/api/v1/shifts/current",
                              headers=owner_headers).json()["id"]
    with get_connection() as conn:
        conn.execute(
            "UPDATE shifts SET opened_at = '2000-01-01T00:00:00Z' "
            "WHERE id = ?",
            (shift_id,),
        )
    result = _evaluate(client, owner_headers)
    mine = [a for a in result["created"]
            if a["entity_id"] == shift_id]
    assert len(mine) == 1
    assert mine[0]["source"] == "SHIFT_STUCK"
    current = client.get("/api/v1/shifts/current",
                         headers=owner_headers).json()
    client.post("/api/v1/shifts/current/close",
                json={"counted_cash": current.get("expected_cash") or 0,
                      "note": "alert test cleanup"},
                headers=owner_headers)
    result = _evaluate(client, owner_headers)
    assert mine[0]["id"] in result["resolved"]


def test_login_spike_and_low_stock(client, owner_headers):
    cust = client.post(
        "/api/v1/customers",
        json={"name": _uniq("Cust"), "pin": "1234"},
        headers=owner_headers,
    ).json()
    _set(client, owner_headers, "alert_login_spike", "2")
    try:
        for _ in range(2):
            client.post("/api/v1/customers/login",
                        json={"identifier": cust["id"], "pin": "bad"})
        result = _evaluate(client, owner_headers)
        spikes = [a for a in result["created"]
                  if a["source"] == "LOGIN_SPIKE"]
        assert len(spikes) == 1
    finally:
        _set(client, owner_headers, "alert_login_spike", "10")
        _resolve_all(client, owner_headers, "LOGIN_SPIKE")
    sku = _uniq("SKU")
    item = client.post(
        "/api/v1/inventory/items",
        json={"sku": sku, "name": sku, "unit_price": 1000,
              "low_stock_at": 5},
        headers=owner_headers,
    )
    assert item.status_code == 201, item.text
    result = _evaluate(client, owner_headers)
    lows = [a for a in result["created"]
            if a["source"] == "LOW_STOCK"
            and a["entity_id"] == item.json()["id"]]
    assert len(lows) == 1
    assert lows[0]["severity"] == "INFO"


def test_ack_resolve_and_filters(client, owner_headers):
    _set(client, owner_headers, "alert_disk_min_mb", "1000000")
    try:
        result = _evaluate(client, owner_headers)
        disks = [a for a in result["created"]
                 if a["source"] == "SERVER_DISK"]
        alert_id = disks[0]["id"]
        acked = client.post(f"/api/v1/alerts/{alert_id}/ack",
                            headers=owner_headers).json()
        assert acked["status"] == "ACKED"
        assert acked["acked_by"] is not None
        # Ack twice is refused:
        assert client.post(f"/api/v1/alerts/{alert_id}/ack",
                           headers=owner_headers).status_code == 409
        assert _alerts(client, owner_headers, "ACKED")["total"] >= 1
        resolved = client.post(f"/api/v1/alerts/{alert_id}/resolve",
                               headers=owner_headers).json()
        assert resolved["status"] == "RESOLVED"
        assert client.get("/api/v1/alerts/ALR-NOPE",
                          headers=owner_headers).status_code == 404
        assert client.get("/api/v1/alerts",
                          params={"status": "NOPE"},
                          headers=owner_headers).status_code == 422
    finally:
        _set(client, owner_headers, "alert_disk_min_mb", "2048")


def test_telegram_test_and_notify(client, owner_headers, monkeypatch):
    # Unconfigured: refused.
    _set(client, owner_headers, "telegram_bot_token", "")
    _set(client, owner_headers, "telegram_chat_id", "")
    assert client.post("/api/v1/alerts/telegram-test",
                       headers=owner_headers).status_code == 409
    _set(client, owner_headers, "telegram_bot_token", "BOT123")
    _set(client, owner_headers, "telegram_chat_id", "CHAT9")
    calls = []

    def fake_post(url, payload):
        calls.append((url, payload))
        return {"ok": True, "result": {"message_id": 42}}

    monkeypatch.setattr(telegram_service, "http_post", fake_post)
    try:
        r = client.post("/api/v1/alerts/telegram-test",
                        headers=owner_headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "message_id": 42}
        assert calls[0][0] == (
            "https://api.telegram.org/botBOT123/sendMessage")
        assert calls[0][1]["chat_id"] == "CHAT9"
        # New WARNING/CRITICAL alerts notify on evaluate:
        _set(client, owner_headers, "alert_disk_min_mb", "1000000")
        result = _evaluate(client, owner_headers)
        assert result["notified"] >= 1
        assert any("SERVER_DISK" in str(c) or "disk" in str(c).lower()
                   for c in calls)
    finally:
        _set(client, owner_headers, "telegram_bot_token", "")
        _set(client, owner_headers, "telegram_chat_id", "")
        _set(client, owner_headers, "alert_disk_min_mb", "2048")


def test_alerts_permissions(client, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert client.get("/api/v1/alerts", headers=viewer).status_code == 200
    assert client.post("/api/v1/alerts/evaluate",
                       headers=viewer).status_code == 200
    assert client.post("/api/v1/alerts/telegram-test",
                       headers=viewer).status_code == 403
