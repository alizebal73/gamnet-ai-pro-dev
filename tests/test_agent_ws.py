import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

from gamenet.server.realtime import hub, presence


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _agent_token(client, headers):
    code = _uniq("WS")
    pc = client.post(
        "/api/v1/pcs",
        json={"device_code": code, "display_name": code},
        headers=headers,
    ).json()
    sec = client.post(f"/api/v1/pcs/{pc['id']}/rotate-secret",
                      headers=headers).json()["secret"]
    auth = client.post(
        "/api/v1/agent/auth",
        json={"device_code": code, "secret": sec},
    ).json()
    return pc, auth["token"]


def test_ws_hello_heartbeat_ping(client, owner_headers):
    presence.reset()
    hub.reset()
    _, token = _agent_token(client, owner_headers)
    with client.websocket_connect(f"/api/v1/agent/ws?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "HELLO"
        assert hello["lease_sec"] == 45
        ws.send_json({"type": "HEARTBEAT",
                      "payload": {"session_id": "SES-9"}})
        ack = ws.receive_json()
        assert ack["type"] == "HEARTBEAT_ACK"
        assert ack["lease_until"] > ack["server_time"]
        assert ack["commands"] == []
        ws.send_json({"type": "PING"})
        assert ws.receive_json()["type"] == "PONG"
        ws.send_json({"type": "BOGUS"})
        err = ws.receive_json()
        assert err["type"] == "ERROR"
    presence.reset()
    hub.reset()


def test_ws_rejects_bad_token(client):
    try:
        with client.websocket_connect("/api/v1/agent/ws?token=nope") as ws:
            ws.receive_text()
        pytest.fail("expected disconnect")
    except WebSocketDisconnect:
        pass


def test_ws_command_push_and_ack(client, owner_headers):
    presence.reset()
    hub.reset()
    pc, token = _agent_token(client, owner_headers)
    with client.websocket_connect(f"/api/v1/agent/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "HELLO"
        q = client.post(
            f"/api/v1/admin/pcs/{pc['id']}/commands",
            json={"type": "MESSAGE", "payload": {"text": "push!"}},
            headers=owner_headers,
        )
        assert q.status_code == 200
        assert q.json()["status"] == "SENT"  # pushed, not pending
        pushed = ws.receive_json()
        assert pushed["type"] == "COMMAND"
        assert pushed["command"]["type"] == "MESSAGE"
        assert pushed["command"]["payload"] == {"text": "push!"}
        ws.send_json({"type": "ACK",
                      "command_id": pushed["command"]["id"],
                      "ok": True, "result": {"shown": True}})
        ack_ok = ws.receive_json()
        assert ack_ok["type"] == "ACK_OK"
        assert ack_ok["status"] == "ACKED"
    listed = client.get(f"/api/v1/admin/pcs/{pc['id']}/commands",
                        headers=owner_headers).json()
    assert listed[0]["status"] == "ACKED"
    presence.reset()
    hub.reset()


def test_offline_queue_delivers_on_next_heartbeat(client, owner_headers):
    presence.reset()
    hub.reset()
    pc, token = _agent_token(client, owner_headers)
    q = client.post(
        f"/api/v1/admin/pcs/{pc['id']}/commands",
        json={"type": "SYNC"}, headers=owner_headers,
    )
    assert q.json()["status"] == "PENDING"  # nobody connected
    with client.websocket_connect(f"/api/v1/agent/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "HELLO"
        ws.send_json({"type": "HEARTBEAT", "payload": {}})
        ack = ws.receive_json()
        assert ack["type"] == "HEARTBEAT_ACK"
        assert len(ack["commands"]) == 1
        assert ack["commands"][0]["type"] == "SYNC"
    presence.reset()
    hub.reset()


def test_ws_disconnect_marks_offline(client, owner_headers):
    presence.reset()
    hub.reset()
    pc, token = _agent_token(client, owner_headers)
    assert hub.is_connected(pc["id"]) is False
    with client.websocket_connect(f"/api/v1/agent/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "HELLO"
        assert hub.is_connected(pc["id"]) is True
        assert presence.get(pc["id"]) is not None
    assert hub.is_connected(pc["id"]) is False
    assert presence.get(pc["id"]) is None
    presence.reset()
    hub.reset()


def test_presence_endpoint(client, owner_headers):
    presence.reset()
    hub.reset()
    pc, token = _agent_token(client, owner_headers)
    client.post(
        "/api/v1/agent/heartbeat",
        json={"session_id": "SES-11", "agent_version": "2.1.0"},
        headers={"Authorization": f"Bearer {token}"},
    )
    items = client.get("/api/v1/admin/presence",
                       headers=owner_headers).json()
    me = next(i for i in items if i["pc_id"] == pc["id"])
    assert me["online"] is True
    assert me["session_id"] == "SES-11"
    assert me["socket_connected"] is False
    with client.websocket_connect(f"/api/v1/agent/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "HELLO"
        items = client.get("/api/v1/admin/presence",
                           headers=owner_headers).json()
        me = next(i for i in items if i["pc_id"] == pc["id"])
        assert me["socket_connected"] is True
    presence.reset()
    hub.reset()
