import uuid
from datetime import UTC, datetime, timedelta

from gamenet.server.db import get_connection, to_utc_iso
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


def _pc(client, headers):
    r = client.post(
        "/api/v1/pcs",
        json={"device_code": _uniq("PC"), "display_name": "Test PC"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


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


def _backdate_anchor(session_id, seconds_ago: int):
    past = to_utc_iso(datetime.now(UTC) - timedelta(seconds=seconds_ago))
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET last_accounted_at = ? WHERE id = ?",
            (past, session_id),
        )


def _active_session(client, headers, customer_id, pc_id):
    s = client.post(
        "/api/v1/sessions",
        json={"customer_id": customer_id, "pc_id": pc_id},
        headers=headers,
    )
    assert s.status_code == 201, s.text
    sid = s.json()["id"]
    assert (
        client.post(f"/api/v1/sessions/{sid}/authorize", json={},
                    headers=headers).status_code == 200
    )
    assert (
        client.post(f"/api/v1/sessions/{sid}/start",
                    headers=headers).status_code == 200
    )
    return sid


def test_full_lifecycle(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])

    paused = client.post(f"/api/v1/sessions/{sid}/pause",
                         json={}, headers=owner_headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"

    resumed = client.post(f"/api/v1/sessions/{sid}/resume",
                          headers=owner_headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "ACTIVE"

    ended = client.post(f"/api/v1/sessions/{sid}/end",
                        json={"reason": "done"}, headers=owner_headers)
    assert ended.status_code == 200
    assert ended.json()["status"] == "ENDED"

    detail = client.get(f"/api/v1/sessions/{sid}",
                        headers=owner_headers).json()
    kinds = [e["kind"] for e in detail["events"]]
    assert kinds == ["CREATED", "AUTHORIZED", "STARTED", "PAUSED",
                     "RESUMED", "ENDED"]


def test_create_requires_credit(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    r = client.post(
        "/api/v1/sessions",
        json={"customer_id": cust["id"], "pc_id": pc["id"]},
        headers=owner_headers,
    )
    assert r.status_code == 409


def test_one_active_session_per_customer(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc1 = _pc(client, owner_headers)
    pc2 = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    _active_session(client, owner_headers, cust["id"], pc1["id"])
    r = client.post(
        "/api/v1/sessions",
        json={"customer_id": cust["id"], "pc_id": pc2["id"]},
        headers=owner_headers,
    )
    assert r.status_code == 409
    assert pc1["id"] in r.json()["detail"]


def test_one_active_session_per_pc(client, owner_headers):
    c1 = _customer(client, owner_headers)
    c2 = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, c1["id"])
    _grant(client, owner_headers, c2["id"])
    _active_session(client, owner_headers, c1["id"], pc["id"])
    r = client.post(
        "/api/v1/sessions",
        json={"customer_id": c2["id"], "pc_id": pc["id"]},
        headers=owner_headers,
    )
    assert r.status_code == 409


def test_authorize_and_start_validation(client, owner_headers):
    cust = _customer(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    s = client.post("/api/v1/sessions", json={"customer_id": cust["id"]},
                    headers=owner_headers).json()
    # Authorize without PC rejected:
    assert (
        client.post(f"/api/v1/sessions/{s['id']}/authorize", json={},
                    headers=owner_headers).status_code == 409
    )
    # Start before authorize rejected:
    assert (
        client.post(f"/api/v1/sessions/{s['id']}/start",
                    headers=owner_headers).status_code == 409
    )


def test_pause_commits_consumption(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"], seconds=3600)
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    _backdate_anchor(sid, 120)
    paused = client.post(f"/api/v1/sessions/{sid}/pause",
                         json={}, headers=owner_headers).json()
    assert paused["status"] == "PAUSED"
    assert paused["total_consumed_sec"] >= 119  # 120s elapsed (±1s)
    assert paused["customer_remaining_sec"] <= 3600 - 119
    assert len(paused["consumptions"]) == 1
    assert paused["consumptions"][0]["kind"] == "TICK"


def test_end_commits_and_releases_pc(client, owner_headers):
    c1 = _customer(client, owner_headers)
    c2 = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, c1["id"], seconds=3600)
    _grant(client, owner_headers, c2["id"], seconds=3600)
    sid = _active_session(client, owner_headers, c1["id"], pc["id"])
    _backdate_anchor(sid, 60)
    ended = client.post(f"/api/v1/sessions/{sid}/end",
                        json={}, headers=owner_headers).json()
    assert ended["status"] == "ENDED"
    assert ended["total_consumed_sec"] >= 59
    # PC is free again:
    sid2 = _active_session(client, owner_headers, c2["id"], pc["id"])
    assert sid2 != sid


def test_transfer_active_session(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc1 = _pc(client, owner_headers)
    pc2 = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"], seconds=3600)
    sid = _active_session(client, owner_headers, cust["id"], pc1["id"])
    _backdate_anchor(sid, 30)
    moved = client.post(
        f"/api/v1/sessions/{sid}/transfer",
        json={"new_pc_id": pc2["id"], "reason": "mouse broken"},
        headers=owner_headers,
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["pc_id"] == pc2["id"]
    assert body["status"] == "ACTIVE"
    assert body["total_consumed_sec"] >= 29  # elapsed committed at transfer
    transfer_events = [e for e in body["events"] if e["kind"] == "TRANSFERRED"]
    assert len(transfer_events) == 1
    assert pc1["id"] in transfer_events[0]["reason"]
    # Old PC is free now:
    c2 = _customer(client, owner_headers)
    _grant(client, owner_headers, c2["id"])
    assert _active_session(client, owner_headers, c2["id"], pc1["id"])


def test_transfer_to_busy_pc_rejected(client, owner_headers):
    c1 = _customer(client, owner_headers)
    c2 = _customer(client, owner_headers)
    pc1 = _pc(client, owner_headers)
    pc2 = _pc(client, owner_headers)
    _grant(client, owner_headers, c1["id"])
    _grant(client, owner_headers, c2["id"])
    sid = _active_session(client, owner_headers, c1["id"], pc1["id"])
    _active_session(client, owner_headers, c2["id"], pc2["id"])
    r = client.post(
        f"/api/v1/sessions/{sid}/transfer",
        json={"new_pc_id": pc2["id"], "reason": "x"},
        headers=owner_headers,
    )
    assert r.status_code == 409


def test_credit_exhausted_auto_end(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"], seconds=60)
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    _backdate_anchor(sid, 3600)  # played way more than owned
    paused = client.post(f"/api/v1/sessions/{sid}/pause",
                         json={}, headers=owner_headers).json()
    assert paused["status"] == "ENDED"
    assert paused["ended_reason"] == "CREDIT_EXHAUSTED"
    assert paused["total_consumed_sec"] == 60
    assert paused["customer_remaining_sec"] == 0


def test_resume_requires_credit(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"], seconds=60)
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    _backdate_anchor(sid, 30)
    assert (
        client.post(f"/api/v1/sessions/{sid}/pause", json={},
                    headers=owner_headers).json()["status"] == "PAUSED"
    )
    with get_connection() as conn:
        left = CreditService(conn).remaining_sec(cust["id"])
        CreditService(conn).consume(
            customer_id=cust["id"], seconds=left,
            ref_type="test", ref_id="drain",
        )
    r = client.post(f"/api/v1/sessions/{sid}/resume", headers=owner_headers)
    assert r.status_code == 409


def test_cancel_created_session(client, owner_headers):
    cust = _customer(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    s = client.post("/api/v1/sessions", json={"customer_id": cust["id"]},
                    headers=owner_headers).json()
    cancelled = client.post(f"/api/v1/sessions/{s['id']}/cancel",
                            json={}, headers=owner_headers).json()
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["total_consumed_sec"] == 0


def test_session_permissions(client, make_user_with_token):
    viewer = make_user_with_token("viewer")
    assert (
        client.post("/api/v1/sessions", json={"customer_id": "x"},
                    headers=viewer).status_code == 403
    )


def test_pc_maintenance_blocks_sessions(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    maint = client.patch(f"/api/v1/pcs/{pc['id']}",
                         json={"status": "MAINTENANCE", "reason": "repair"},
                         headers=owner_headers)
    assert maint.status_code == 200
    r = client.post(
        "/api/v1/sessions",
        json={"customer_id": cust["id"], "pc_id": pc["id"]},
        headers=owner_headers,
    )
    assert r.status_code == 409
    # Heartbeat-driven statuses cannot be set manually:
    bad = client.patch(f"/api/v1/pcs/{pc['id']}",
                       json={"status": "BUSY"}, headers=owner_headers)
    assert bad.status_code == 422
    # Release back to pool:
    back = client.patch(f"/api/v1/pcs/{pc['id']}",
                        json={"status": "OFFLINE"}, headers=owner_headers)
    assert back.json()["status"] == "OFFLINE"


def test_retire_guarded_and_secret_rotation(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    r = client.patch(f"/api/v1/pcs/{pc['id']}",
                     json={"status": "RETIRED"}, headers=owner_headers)
    assert r.status_code == 409
    client.post(f"/api/v1/sessions/{sid}/end", json={},
                headers=owner_headers)
    r = client.patch(f"/api/v1/pcs/{pc['id']}",
                     json={"status": "RETIRED"}, headers=owner_headers)
    assert r.status_code == 200
    # Device secret shown once, hash stored:
    sec = client.post(f"/api/v1/pcs/{pc['id']}/rotate-secret",
                      headers=owner_headers).json()
    assert len(sec["secret"]) > 20
    with get_connection() as conn:
        row = conn.execute(
            "SELECT secret_hash FROM device_credentials WHERE pc_id = ?",
            (pc["id"],),
        ).fetchone()
    assert row is not None and row["secret_hash"] != sec["secret"]


def test_duplicate_device_code_rejected(client, owner_headers):
    pc = _pc(client, owner_headers)
    r = client.post(
        "/api/v1/pcs",
        json={"device_code": pc["device_code"], "display_name": "Dup"},
        headers=owner_headers,
    )
    assert r.status_code == 409
