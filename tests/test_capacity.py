import uuid
from datetime import UTC, datetime, timedelta

from gamenet.server.db import get_connection, to_utc_iso


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


def _window(hours_ahead=1, duration_hours=2):
    start = datetime.now(UTC) + timedelta(hours=hours_ahead)
    return to_utc_iso(start), to_utc_iso(start + timedelta(
        hours=duration_hours))


def _book(client, headers, customer_id, pc_id, starts_at=None,
          ends_at=None):
    starts_at, ends_at = starts_at or _window()[0], ends_at or _window()[1]
    return client.post(
        "/api/v1/reservations",
        json={"customer_id": customer_id, "pc_id": pc_id,
              "starts_at": starts_at, "ends_at": ends_at},
        headers=headers,
    )


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


# ---------- reservations ----------

def test_book_and_get(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    starts_at, ends_at = _window()
    r = _book(client, owner_headers, cust["id"], pc["id"], starts_at,
              ends_at)
    assert r.status_code == 201, r.text
    assert r.json()["id"].startswith("RES-")
    assert r.json()["status"] == "BOOKED"
    got = client.get(f"/api/v1/reservations/{r.json()['id']}",
                     headers=owner_headers).json()
    assert got["starts_at"] == starts_at
    assert client.get("/api/v1/reservations/RES-NOPE",
                      headers=owner_headers).status_code == 404


def test_overlapping_book_rejected(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    starts_at, ends_at = _window()
    assert _book(client, owner_headers, cust["id"], pc["id"], starts_at,
                 ends_at).status_code == 201
    # Overlap:
    clash = _book(client, owner_headers, cust["id"], pc["id"],
                  to_utc_iso(datetime.now(UTC) + timedelta(
                      hours=2)),
                  to_utc_iso(datetime.now(UTC) + timedelta(hours=4)))
    assert clash.status_code == 409
    # Back-to-back is fine (end == start):
    ok = _book(client, owner_headers, cust["id"], pc["id"], ends_at,
               to_utc_iso(datetime.now(UTC) + timedelta(hours=5)))
    assert ok.status_code == 201, ok.text
    # Different PC, same window: fine.
    pc2 = _pc(client, owner_headers)
    assert _book(client, owner_headers, cust["id"], pc2["id"],
                 starts_at, ends_at).status_code == 201


def test_book_validation(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    starts_at, ends_at = _window()
    assert _book(client, owner_headers, cust["id"], pc["id"], ends_at,
                 starts_at).status_code == 400  # ends before starts
    past = _book(client, owner_headers, cust["id"], pc["id"],
                 to_utc_iso(datetime.now(UTC) - timedelta(hours=3)),
                 to_utc_iso(datetime.now(UTC) - timedelta(hours=1)))
    assert past.status_code == 400
    assert _book(client, owner_headers, "CUS-NOPE", pc["id"], starts_at,
                 ends_at).status_code == 404
    junk = client.post(
        "/api/v1/reservations",
        json={"customer_id": cust["id"], "pc_id": pc["id"],
              "starts_at": "tomorrow-ish", "ends_at": ends_at},
        headers=owner_headers,
    )
    assert junk.status_code == 400


def test_cancel_no_show_and_filters(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    r1 = _book(client, owner_headers, cust["id"], pc["id"]).json()
    starts2, ends2 = _window(hours_ahead=5, duration_hours=1)
    r2 = _book(client, owner_headers, cust["id"], pc["id"], starts2,
               ends2).json()
    c = client.post(f"/api/v1/reservations/{r1['id']}/cancel",
                    json={"reason": "changed plans"},
                    headers=owner_headers)
    assert c.json()["status"] == "CANCELLED"
    assert c.json()["cancel_reason"] == "changed plans"
    # A cancelled window frees the PC:
    assert _book(client, owner_headers, cust["id"], pc["id"],
                 r1["starts_at"], r1["ends_at"]).status_code == 201
    n = client.post(f"/api/v1/reservations/{r2['id']}/no-show",
                    headers=owner_headers)
    assert n.json()["status"] == "NO_SHOW"
    booked = client.get("/api/v1/reservations",
                        params={"status": "BOOKED"},
                        headers=owner_headers).json()
    assert r1["id"] not in [r["id"] for r in booked]
    mine = client.get("/api/v1/reservations",
                      params={"customer_id": cust["id"]},
                      headers=owner_headers).json()
    assert len(mine) >= 3


def test_seat_creates_session(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    res = _book(client, owner_headers, cust["id"], pc["id"]).json()
    seated = client.post(f"/api/v1/reservations/{res['id']}/seat",
                         headers=owner_headers)
    assert seated.status_code == 200, seated.text
    assert seated.json()["reservation"]["status"] == "SEATED"
    assert seated.json()["session"]["status"] == "AUTHORIZED"
    assert seated.json()["session"]["pc_id"] == pc["id"]
    again = client.post(f"/api/v1/reservations/{res['id']}/seat",
                        headers=owner_headers)
    assert again.status_code == 409


def test_seat_without_credit_fails_and_stays_booked(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    res = _book(client, owner_headers, cust["id"], pc["id"]).json()
    seated = client.post(f"/api/v1/reservations/{res['id']}/seat",
                         headers=owner_headers)
    assert seated.status_code == 409
    got = client.get(f"/api/v1/reservations/{res['id']}",
                     headers=owner_headers).json()
    assert got["status"] == "BOOKED"


def test_past_reservations_expire_lazily(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    res = _book(client, owner_headers, cust["id"], pc["id"]).json()
    with get_connection() as conn:
        conn.execute(
            "UPDATE reservations SET starts_at = '2000-01-01T00:00:00Z', "
            "ends_at = '2000-01-02T00:00:00Z' WHERE id = ?",
            (res["id"],),
        )
    got = client.get(f"/api/v1/reservations/{res['id']}",
                     headers=owner_headers).json()
    assert got["status"] == "EXPIRED"


# ---------- queue ----------

def _join(client, headers, customer_id, **kw):
    body = {"customer_id": customer_id}
    body.update(kw)
    return client.post("/api/v1/queue", json=body, headers=headers)


def test_queue_fifo_and_positions(client, owner_headers):
    a = _customer(client, owner_headers)
    b = _customer(client, owner_headers)
    assert _join(client, owner_headers, a["id"]).status_code == 201
    assert _join(client, owner_headers, b["id"]).status_code == 201
    items = client.get("/api/v1/queue", headers=owner_headers).json()
    mine = [e for e in items
            if e["customer_id"] in (a["id"], b["id"])]
    assert [e["customer_id"] for e in mine] == [a["id"], b["id"]]
    assert mine[0]["position"] == 1
    assert mine[0]["customer_name"] == a["name"]
    # Double join refused:
    assert _join(client, owner_headers, a["id"]).status_code == 409


def test_queue_priority_and_call_cancel(client, owner_headers):
    a = _customer(client, owner_headers)
    b = _customer(client, owner_headers)
    _join(client, owner_headers, a["id"])
    _join(client, owner_headers, b["id"], priority=5)
    items = client.get("/api/v1/queue", headers=owner_headers).json()
    mine = [e for e in items
            if e["customer_id"] in (a["id"], b["id"])]
    assert mine[0]["customer_id"] == b["id"]  # priority first
    called = client.post(f"/api/v1/queue/{mine[0]['id']}/call",
                         headers=owner_headers).json()
    assert called["status"] == "CALLED"
    assert called["called_at"] is not None
    cancelled = client.post(f"/api/v1/queue/{mine[1]['id']}/cancel",
                            headers=owner_headers).json()
    assert cancelled["status"] == "CANCELLED"
    items = client.get("/api/v1/queue", headers=owner_headers).json()
    assert mine[1]["id"] not in [e["id"] for e in items]


def test_queue_vip_boost_opt_in(client, owner_headers):
    plain = _customer(client, owner_headers)
    vip = _customer(client, owner_headers)
    plan = client.post(
        "/api/v1/vip-plans",
        json={"name": _uniq("VIP"), "duration_days": 30,
              "price": 1500000, "discount_pct": 0},
        headers=owner_headers,
    ).json()
    sale = client.post(
        "/api/v1/sales",
        json={"customer_id": vip["id"],
              "items": [{"kind": "VIP", "ref_id": plan["id"]}]},
        headers=owner_headers,
    ).json()
    client.post(f"/api/v1/sales/{sale['id']}/payments",
                json={"method": "CASH", "amount": sale["total"]},
                headers=owner_headers)
    client.post(f"/api/v1/sales/{sale['id']}/confirm",
                headers=owner_headers)
    _join(client, owner_headers, plain["id"])
    _join(client, owner_headers, vip["id"])
    try:
        client.put("/api/v1/settings/queue_vip_priority",
                   json={"value": "1"}, headers=owner_headers)
        items = client.get("/api/v1/queue", headers=owner_headers).json()
        mine = [e for e in items if e["customer_id"] in (
            plain["id"], vip["id"])]
        assert mine[0]["customer_id"] == vip["id"]
        assert mine[0]["vip_boosted"] is True
    finally:
        client.put("/api/v1/settings/queue_vip_priority",
                   json={"value": "0"}, headers=owner_headers)
        for cid in (plain["id"], vip["id"]):
            items = client.get("/api/v1/queue",
                               headers=owner_headers).json()
            for e in items:
                if e["customer_id"] == cid:
                    client.post(f"/api/v1/queue/{e['id']}/cancel",
                                headers=owner_headers)


def test_queue_seat_and_expiry(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    entry = _join(client, owner_headers, cust["id"],
                  pc_id=pc["id"]).json()
    seated = client.post(f"/api/v1/queue/{entry['id']}/seat", json={},
                         headers=owner_headers)
    assert seated.status_code == 200, seated.text
    assert seated.json()["entry"]["status"] == "SEATED"
    assert seated.json()["session"]["pc_id"] == pc["id"]
    # Expiry: backdate another entry beyond the window.
    cust2 = _customer(client, owner_headers)
    entry2 = _join(client, owner_headers, cust2["id"]).json()
    with get_connection() as conn:
        conn.execute(
            "UPDATE queue_entries SET created_at = '2000-01-01T00:00:00Z' "
            "WHERE id = ?",
            (entry2["id"],),
        )
    items = client.get("/api/v1/queue", headers=owner_headers).json()
    assert entry2["id"] not in [e["id"] for e in items]


# ---------- groups ----------

def test_group_lifecycle_and_end_all(client, owner_headers):
    cust_a = _customer(client, owner_headers)
    cust_b = _customer(client, owner_headers)
    pc_a = _pc(client, owner_headers)
    pc_b = _pc(client, owner_headers)
    _grant(client, owner_headers, cust_a["id"])
    _grant(client, owner_headers, cust_b["id"])
    sid_a = _active_session(client, owner_headers, cust_a["id"],
                            pc_a["id"])
    sid_b = _active_session(client, owner_headers, cust_b["id"],
                            pc_b["id"])
    grp = client.post("/api/v1/session-groups", json={"name": "LAN party"},
                      headers=owner_headers)
    assert grp.status_code == 201, grp.text
    gid = grp.json()["id"]
    assert gid.startswith("GRP-")
    client.post(f"/api/v1/session-groups/{gid}/members",
                json={"session_id": sid_a}, headers=owner_headers)
    detail = client.post(
        f"/api/v1/session-groups/{gid}/members",
        json={"session_id": sid_b}, headers=owner_headers).json()
    assert len(detail["members"]) == 2
    # One member in two groups is refused:
    grp2 = client.post("/api/v1/session-groups", json={},
                       headers=owner_headers).json()
    dup = client.post(f"/api/v1/session-groups/{grp2['id']}/members",
                      json={"session_id": sid_a},
                      headers=owner_headers)
    assert dup.status_code == 409
    result = client.post(f"/api/v1/session-groups/{gid}/end-all",
                         json={"reason": "party over"},
                         headers=owner_headers).json()
    assert sorted(result["ended"]) == sorted([sid_a, sid_b])
    assert result["group"]["status"] == "CLOSED"
    for sid in (sid_a, sid_b):
        s = client.get(f"/api/v1/sessions/{sid}",
                       headers=owner_headers).json()
        assert s["status"] == "ENDED"
        assert s["ended_reason"] == "party over"


def test_group_remove_member(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    gid = client.post("/api/v1/session-groups", json={},
                      headers=owner_headers).json()["id"]
    client.post(f"/api/v1/session-groups/{gid}/members",
                json={"session_id": sid}, headers=owner_headers)
    removed = client.delete(
        f"/api/v1/session-groups/{gid}/members/{sid}",
        headers=owner_headers).json()
    assert removed["members"] == []
    s = client.get(f"/api/v1/sessions/{sid}",
                   headers=owner_headers).json()
    assert s["status"] == "ACTIVE"  # session itself untouched


def test_capacity_permissions(client, owner_headers, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert client.post("/api/v1/reservations", json={},
                       headers=viewer).status_code == 403
    assert client.get("/api/v1/queue", headers=viewer).status_code == 403
    assert client.post("/api/v1/session-groups", json={},
                       headers=viewer).status_code == 403
