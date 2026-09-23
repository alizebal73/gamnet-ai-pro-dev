import time
import uuid

import pytest

from gamenet.server.db import get_connection
from gamenet.server.realtime import presence
from gamenet.server.workers.lease_monitor import check_leases, reset_handled


@pytest.fixture(autouse=True)
def _clean_state():
    presence.reset()
    reset_handled()
    yield
    presence.reset()
    reset_handled()


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
    pc = client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=headers,
    ).json()
    sec = client.post(f"/api/v1/pcs/{pc['id']}/rotate-secret",
                      headers=headers).json()["secret"]
    return pc, code, sec


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
    )
    assert s.status_code == 201, s.text
    sid = s.json()["id"]
    client.post(f"/api/v1/sessions/{sid}/authorize", json={},
                headers=headers)
    client.post(f"/api/v1/sessions/{sid}/start", headers=headers)
    return sid


def _agent_token(client, device_code, secret):
    return client.post(
        "/api/v1/agent/auth",
        json={"device_code": device_code, "secret": secret},
    ).json()["token"]


def _beat(client, token, **payload):
    return client.post(
        "/api/v1/agent/heartbeat", json=payload,
        headers={"Authorization": f"Bearer {token}"},
    ).json()


def _cmd_types(client, headers, pc_id):
    cmds = client.get(f"/api/v1/admin/pcs/{pc_id}/commands",
                      headers=headers).json()
    return [c["type"] for c in reversed(cmds)]  # chronological


def test_lifecycle_emits_lock_unlock(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc, _, _ = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    assert _cmd_types(client, owner_headers, pc["id"]) == ["UNLOCK"]
    client.post(f"/api/v1/sessions/{sid}/pause", json={}, headers=owner_headers)
    assert _cmd_types(client, owner_headers, pc["id"]) == ["UNLOCK", "LOCK"]
    client.post(f"/api/v1/sessions/{sid}/resume", headers=owner_headers)
    assert _cmd_types(client, owner_headers, pc["id"]) == [
        "UNLOCK", "LOCK", "UNLOCK"]
    client.post(f"/api/v1/sessions/{sid}/end", json={},
                headers=owner_headers)
    assert _cmd_types(client, owner_headers, pc["id"]) == [
        "UNLOCK", "LOCK", "UNLOCK", "LOCK"]


def test_transfer_emits_lock_and_unlock(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc_a, _, _ = _pc(client, owner_headers)
    pc_b, _, _ = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc_a["id"])
    r = client.post(
        f"/api/v1/sessions/{sid}/transfer",
        json={"new_pc_id": pc_b["id"], "reason": "broken chair"},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    assert _cmd_types(client, owner_headers, pc_a["id"]) == ["UNLOCK", "LOCK"]
    assert _cmd_types(client, owner_headers, pc_b["id"]) == ["UNLOCK"]


def test_cancel_emits_lock(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc, _, _ = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    s = client.post(
        "/api/v1/sessions",
        json={"customer_id": cust["id"], "pc_id": pc["id"]},
        headers=owner_headers,
    ).json()
    client.post(f"/api/v1/sessions/{s['id']}/authorize", json={},
                headers=owner_headers)
    client.post(f"/api/v1/sessions/{s['id']}/cancel",
                json={"reason": "no-show"}, headers=owner_headers)
    assert _cmd_types(client, owner_headers, pc["id"]) == ["LOCK"]


def test_lease_expiry_auto_pauses_and_locks(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc, code, secret = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    token = _agent_token(client, code, secret)
    _beat(client, token, session_id=sid)
    with get_connection() as conn:
        summary = check_leases(conn, now_ts=time.time() + 3600)
    assert summary["paused"] == [sid]
    detail = client.get(f"/api/v1/sessions/{sid}",
                        headers=owner_headers).json()
    assert detail["status"] == "PAUSED"
    pause_ev = [e for e in detail["events"] if e["kind"] == "PAUSED"][-1]
    assert pause_ev["reason"] == "LINK_LOST"
    assert pause_ev["actor_user_id"] is None
    assert _cmd_types(client, owner_headers, pc["id"]) == ["UNLOCK", "LOCK"]
    # Second tick with the same clock: no duplicate pause or LOCK.
    with get_connection() as conn:
        again = check_leases(conn, now_ts=time.time() + 3600)
    assert again["paused"] == []
    assert _cmd_types(client, owner_headers, pc["id"]) == ["UNLOCK", "LOCK"]


def test_reconnect_then_manual_resume(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc, code, secret = _pc(client, owner_headers)
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    token = _agent_token(client, code, secret)
    _beat(client, token, session_id=sid)
    with get_connection() as conn:
        check_leases(conn, now_ts=time.time() + 3600)
    # Agent comes back: heartbeat delivers LOCK + shows PAUSED session.
    back = _beat(client, token, session_id=sid)
    # UNLOCK was already consumed by the pre-outage heartbeat.
    assert [c["type"] for c in back["commands"]] == ["LOCK"]
    assert back["session"]["id"] == sid
    assert back["session"]["status"] == "PAUSED"
    # Operator resumes manually: UNLOCK queued for the next heartbeat.
    r = client.post(f"/api/v1/sessions/{sid}/resume",
                    headers=owner_headers)
    assert r.status_code == 200, r.text
    nxt = _beat(client, token, session_id=sid)
    assert [c["type"] for c in nxt["commands"]] == ["UNLOCK"]
    assert nxt["session"]["status"] == "ACTIVE"


def test_lease_ignores_idle_or_paused_pcs(client, owner_headers):
    pc, code, secret = _pc(client, owner_headers)
    token = _agent_token(client, code, secret)
    _beat(client, token)
    with get_connection() as conn:
        summary = check_leases(conn, now_ts=time.time() + 3600)
    assert summary["checked"] == 1
    assert summary["paused"] == []


def test_heartbeat_carries_session_sync(client, owner_headers):
    cust = _customer(client, owner_headers)
    pc, code, secret = _pc(client, owner_headers)
    token = _agent_token(client, code, secret)
    assert _beat(client, token)["session"] is None
    _grant(client, owner_headers, cust["id"])
    sid = _active_session(client, owner_headers, cust["id"], pc["id"])
    sync = _beat(client, token)
    assert sync["session"]["id"] == sid
    assert sync["session"]["status"] == "ACTIVE"
    assert sync["session"]["customer_id"] == cust["id"]


def test_check_leases_flushes_presence(client, owner_headers):
    pc, code, secret = _pc(client, owner_headers)
    token = _agent_token(client, code, secret)
    _beat(client, token)
    with get_connection() as conn:
        summary = check_leases(conn)
        row = conn.execute("SELECT last_seen_at FROM pcs WHERE id = ?",
                           (pc["id"],)).fetchone()
    assert summary["flushed"] >= 1
    assert row["last_seen_at"] is not None


def test_pc_lock_roundtrip(client, owner_headers):
    pc, code, secret = _pc(client, owner_headers)
    token = _agent_token(client, code, secret)
    q = client.post(
        f"/api/v1/admin/pcs/{pc['id']}/commands",
        json={"type": "LOCK", "payload": {"reason": "operator"}},
        headers=owner_headers,
    )
    assert q.status_code == 200
    beat = _beat(client, token)
    assert beat["commands"][0]["type"] == "LOCK"
    ack = client.post(
        f"/api/v1/agent/commands/{beat['commands'][0]['id']}/ack",
        json={"ok": True}, headers={"Authorization": f"Bearer {token}"},
    )
    assert ack.json()["status"] == "ACKED"
