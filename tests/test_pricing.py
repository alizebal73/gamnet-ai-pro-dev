import uuid
from datetime import datetime, timedelta


def _cls(prefix: str = "T") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _quote(client, headers, duration_sec, pc_class=None, at=None):
    body = {"duration_sec": duration_sec}
    if pc_class:
        body["pc_class"] = pc_class
    if at:
        body["at"] = at
    return client.post("/api/v1/pricing/quote", json=body, headers=headers)


def _make_rule(client, headers, **fields):
    base = {"name": f"R-{uuid.uuid4().hex[:6]}", "kind": "PER_HOUR", "price": 80000}
    base.update(fields)
    resp = client.post("/api/v1/pricing/rules", json=base, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _at(hour: int, minute: int = 0, weekday: int | None = None) -> str:
    d = datetime.now().astimezone()
    if weekday is not None:
        delta = (weekday - d.weekday()) % 7 or 7
        d = d + timedelta(days=delta)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def test_default_hourly_quote(client, owner_headers):
    assert _quote(client, owner_headers, 3600).json()["total"] == 80000
    assert _quote(client, owner_headers, 1800).json()["total"] == 40000
    assert _quote(client, owner_headers, 5400).json()["total"] == 120000  # 90 min


def test_flat_bundle_wins_over_hourly(client, owner_headers):
    cls = _cls()
    _make_rule(
        client, owner_headers, kind="FLAT", duration_sec=7200,
        price=140000, pc_class=cls,
    )
    assert _quote(client, owner_headers, 7200, cls).json()["total"] == 140000
    # Other durations still use hourly fallback:
    assert _quote(client, owner_headers, 3600, cls).json()["total"] == 80000


def test_offpeak_multiplier_with_overnight_window(client, owner_headers):
    cls = _cls()
    _make_rule(
        client, owner_headers, kind="MULTIPLIER", price=None, factor_pct=50,
        pc_class=cls, window_start_min=22 * 60, window_end_min=6 * 60,
    )
    assert _quote(client, owner_headers, 3600, cls, _at(23)).json()["total"] == 40000
    assert _quote(client, owner_headers, 3600, cls, _at(12)).json()["total"] == 80000


def test_weekend_scope_uses_iran_weekend(client, owner_headers):
    cls = _cls()
    _make_rule(
        client, owner_headers, kind="MULTIPLIER", price=None, factor_pct=50,
        pc_class=cls, scope="WEEKEND",
    )
    thursday = _quote(client, owner_headers, 3600, cls, _at(12, weekday=3)).json()
    sunday = _quote(client, owner_headers, 3600, cls, _at(12, weekday=6)).json()
    assert thursday["total"] == 40000
    assert thursday["snapshot"]["scope"] == "WEEKEND"
    assert sunday["total"] == 80000
    assert sunday["snapshot"]["scope"] == "WEEKDAY"


def test_pc_class_scoping(client, owner_headers):
    cls = _cls()
    _make_rule(
        client, owner_headers, kind="FLAT", duration_sec=3600,
        price=50000, pc_class=cls,
    )
    assert _quote(client, owner_headers, 3600, cls).json()["total"] == 50000
    assert _quote(client, owner_headers, 3600).json()["total"] == 80000


def test_lower_priority_number_wins(client, owner_headers):
    cls = _cls()
    _make_rule(client, owner_headers, price=100000, pc_class=cls, priority=10)
    _make_rule(client, owner_headers, price=90000, pc_class=cls, priority=5)
    assert _quote(client, owner_headers, 3600, cls).json()["total"] == 90000


def test_snapshot_captures_inputs_and_rules(client, owner_headers):
    cls = _cls()
    rule = _make_rule(
        client, owner_headers, kind="FLAT", duration_sec=3600,
        price=70000, pc_class=cls,
    )
    snap = _quote(client, owner_headers, 3600, cls).json()["snapshot"]
    assert snap["duration_sec"] == 3600
    assert snap["pc_class"] == cls
    assert snap["currency_unit"] == "RIAL"
    assert snap["base"]["rule_id"] == rule["id"]
    assert snap["total"] == 70000


def test_invalid_rule_rejected(client, owner_headers):
    # FLAT without duration:
    r = client.post(
        "/api/v1/pricing/rules",
        json={"name": "Bad", "kind": "FLAT", "price": 100},
        headers=owner_headers,
    )
    assert r.status_code == 422
    # PER_HOUR with factor:
    r = client.post(
        "/api/v1/pricing/rules",
        json={"name": "Bad", "kind": "PER_HOUR", "price": 100, "factor_pct": 50},
        headers=owner_headers,
    )
    assert r.status_code == 422


def test_quote_permissions(client, make_user_with_token):
    operator = make_user_with_token("operator")
    assert _quote(client, operator, 3600).status_code == 200
    viewer = make_user_with_token("viewer")
    assert _quote(client, viewer, 3600).status_code == 403
    r = client.post(
        "/api/v1/pricing/rules",
        json={"name": "X", "kind": "PER_HOUR", "price": 1},
        headers=operator,
    )
    assert r.status_code == 403  # operator lacks settings.edit


def test_settings_update_and_audit(client, owner_headers):
    r = client.put(
        "/api/v1/settings/store_name",
        json={"value": "GameNet 98"},
        headers=owner_headers,
    )
    assert r.status_code == 200
    assert r.json()["value"] == "GameNet 98"

    bad = client.put(
        "/api/v1/settings/price_per_hour",
        json={"value": "not-a-number"},
        headers=owner_headers,
    )
    assert bad.status_code == 422

    unknown = client.put(
        "/api/v1/settings/nope",
        json={"value": "x"},
        headers=owner_headers,
    )
    assert unknown.status_code == 422


def test_price_per_hour_fallback_change(client, owner_headers):
    try:
        client.put(
            "/api/v1/settings/price_per_hour",
            json={"value": "90000"},
            headers=owner_headers,
        )
        assert _quote(client, owner_headers, 3600).json()["total"] == 90000
    finally:
        client.put(
            "/api/v1/settings/price_per_hour",
            json={"value": "80000"},
            headers=owner_headers,
        )
    assert _quote(client, owner_headers, 3600).json()["total"] == 80000
