import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gamenet.client_agent.agent import Agent
from gamenet.client_agent.config import AgentConfig
from gamenet.client_agent.platform_layer import MockPlatform
from gamenet.client_agent.transport import (
    AgentAuthError,
    RestTransport,
    TransportError,
)


class FakeTransport:
    def __init__(self):
        self.auth_calls = []
        self.beats = []
        self.acks = []
        self.auth_script = []
        self.beat_script = []
        self.ack_script = []

    def authenticate(self, device_code, secret, agent_version):
        self.auth_calls.append((device_code, secret, agent_version))
        if self.auth_script:
            item = self.auth_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {"token": "TOK", "pc_id": "PC-1"}

    def heartbeat(self, token, payload):
        self.beats.append(payload)
        if not self.beat_script:
            return {"server_time": "t", "commands": [], "session": None}
        item = self.beat_script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def ack(self, token, command_id, ok, result):
        self.acks.append((command_id, ok, result))
        if self.ack_script:
            item = self.ack_script.pop(0)
            if isinstance(item, Exception):
                raise item
        return {"status": "ACKED"}


def _config(tmp_path, **over):
    args = {"server_url": "http://127.0.0.1:9", "device_code": "PC-1",
            "secret": "s", "data_dir": str(tmp_path)}
    args.update(over)
    return AgentConfig(**args)


def _cmd(cid, type, payload=None):
    return {"id": cid, "type": type, "payload": payload or {}}


def test_first_tick_authenticates_and_beats(tmp_path):
    agent = Agent(_config(tmp_path), FakeTransport(), MockPlatform())
    assert agent.locked is True  # boots locked
    summary = agent.tick()
    assert summary["authed"] is True
    assert agent._transport.auth_calls[0][0] == "PC-1"
    assert agent._transport.beats[0]["agent_version"] == "0.1.0"
    assert agent.session_id is None


def test_lock_unlock_commands(tmp_path):
    fake, platform = FakeTransport(), MockPlatform()
    agent = Agent(_config(tmp_path), fake, platform)
    fake.beat_script.append(
        {"server_time": "t",
         "commands": [_cmd("C1", "LOCK", {"reason": "PAUSED"})],
         "session": {"id": "S1", "status": "PAUSED"}})
    agent.tick()
    assert ("lock", "PAUSED") in platform.calls
    assert agent.locked is True
    assert fake.acks == [("C1", True, {"ok": True})]
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C2", "UNLOCK",
                                              {"session_id": "S1"})],
         "session": {"id": "S1", "status": "ACTIVE"}})
    agent.tick()
    assert ("unlock", "S1") in platform.calls
    assert agent.locked is False


def test_unknown_command_acked_as_failed(tmp_path):
    fake, platform = FakeTransport(), MockPlatform()
    agent = Agent(_config(tmp_path), fake, platform)
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C9", "FORMAT_DISK")],
         "session": None})
    agent.tick()
    assert fake.acks[0][0] == "C9"
    assert fake.acks[0][1] is False
    assert "Unknown command" in fake.acks[0][2]["error"]
    assert agent.locked is True


def test_401_triggers_reauth(tmp_path):
    fake = FakeTransport()
    agent = Agent(_config(tmp_path), fake, MockPlatform())
    agent.tick()
    assert len(fake.auth_calls) == 1
    fake.beat_script.append(AgentAuthError("expired"))
    with pytest.raises(AgentAuthError):
        agent.tick()
    agent._token = None  # what run_forever does on AgentAuthError
    agent.tick()
    assert len(fake.auth_calls) == 2


def test_backoff_on_transport_error(tmp_path):
    sleeps = []
    stop = threading.Event()
    fake = FakeTransport()

    orig_beat = fake.heartbeat

    def _counting_beat(token, payload):
        try:
            return orig_beat(token, payload)
        finally:
            if len(fake.beats) >= 3:
                stop.set()

    fake.heartbeat = _counting_beat
    fake.beat_script.extend([TransportError("down"),
                             TransportError("down"),
                             {"server_time": "t", "commands": [],
                              "session": None}])
    agent = Agent(_config(tmp_path, heartbeat_interval_sec=0,
                          max_backoff_sec=60),
                  fake, MockPlatform(), sleep=sleeps.append)
    agent.run_forever(stop)
    assert sleeps[:2] == [2, 4]  # exponential backoff, then success


def test_pending_ack_retried_next_tick(tmp_path):
    fake = FakeTransport()
    agent = Agent(_config(tmp_path), fake, MockPlatform())
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C1", "SYNC")],
         "session": None})
    fake.ack_script.append(TransportError("down"))
    summary = agent.tick()
    assert summary["errors"] != []
    assert len(agent.pending_acks) == 1
    summary2 = agent.tick()
    assert summary2["acked"] == ["C1"]
    assert agent.pending_acks == []


def test_sync_paused_locks_without_command(tmp_path):
    fake, platform = FakeTransport(), MockPlatform()
    agent = Agent(_config(tmp_path), fake, platform)
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C1", "UNLOCK")],
         "session": {"id": "S1", "status": "ACTIVE"}})
    agent.tick()
    assert agent.locked is False
    fake.beat_script.append(
        {"server_time": "t", "commands": [],
         "session": {"id": "S1", "status": "PAUSED"}})
    agent.tick()
    assert agent.locked is True
    assert platform.calls[-1][0] == "lock"


def test_sync_active_never_unlocks(tmp_path):
    fake = FakeTransport()
    agent = Agent(_config(tmp_path), fake, MockPlatform())
    fake.beat_script.append(
        {"server_time": "t", "commands": [],
         "session": {"id": "S1", "status": "ACTIVE"}})
    agent.tick()
    assert agent.locked is True  # only UNLOCK unlocks
    assert agent.session_id == "S1"


def test_session_gone_locks_and_clears(tmp_path):
    fake, platform = FakeTransport(), MockPlatform()
    agent = Agent(_config(tmp_path), fake, platform)
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C1", "UNLOCK")],
         "session": {"id": "S1", "status": "ACTIVE"}})
    agent.tick()
    assert agent.locked is False
    fake.beat_script.append(
        {"server_time": "t", "commands": [], "session": None})
    agent.tick()
    assert agent.locked is True
    assert agent.session_id is None
    assert platform.calls[-1] == ("lock", "SESSION_GONE")


def test_state_survives_restart(tmp_path):
    fake = FakeTransport()
    agent = Agent(_config(tmp_path), fake, MockPlatform())
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C1", "SYNC")],
         "session": None})
    fake.ack_script.append(TransportError("down"))
    agent.tick()
    assert len(agent.pending_acks) == 1
    # New process, same data dir: still locked, ACK still pending.
    fake2 = FakeTransport()
    agent2 = Agent(_config(tmp_path), fake2, MockPlatform())
    assert agent2.locked is True
    assert len(agent2.pending_acks) == 1
    assert agent2.tick()["acked"] == ["C1"]


def test_platform_exception_reported_not_raised(tmp_path):
    class Exploding(MockPlatform):
        def lock(self, reason):
            raise OSError("no desktop")

    fake = FakeTransport()
    agent = Agent(_config(tmp_path), fake, Exploding())
    fake.beat_script.append(
        {"server_time": "t", "commands": [_cmd("C1", "LOCK")],
         "session": None})
    agent.tick()  # must not raise
    assert fake.acks[0][1] is False
    assert "OSError" in fake.acks[0][2]["error"]


def test_config_validation(tmp_path):
    with pytest.raises(ValueError):
        AgentConfig(device_code="", secret="s").validate()
    with pytest.raises(ValueError):
        AgentConfig(device_code="P", secret="").validate()
    with pytest.raises(ValueError):
        AgentConfig(device_code="P", secret="s",
                    server_url="ftp://x").validate()
    AgentConfig(device_code="P", secret="s").validate()


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if _Handler.mode == "denied":
            return self._send(401, {"detail": "nope"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        return self._send(200, {"echo": body,
                               "auth": self.headers.get("Authorization")})

    def log_message(self, *args):
        pass


def _live_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_rest_transport_roundtrip():
    server = _live_server()
    try:
        _Handler.mode = "ok"
        transport = RestTransport(
            f"http://127.0.0.1:{server.server_port}", timeout_sec=5)
        resp = transport.heartbeat("TOK", {"a": 1})
        assert resp["echo"] == {"a": 1}
        assert resp["auth"] == "Bearer TOK"
    finally:
        server.shutdown()


def test_rest_transport_401_maps_to_auth_error():
    server = _live_server()
    try:
        _Handler.mode = "denied"
        transport = RestTransport(
            f"http://127.0.0.1:{server.server_port}", timeout_sec=5)
        with pytest.raises(AgentAuthError):
            transport.heartbeat("BAD", {})
    finally:
        _Handler.mode = "ok"
        server.shutdown()


def test_rest_transport_unreachable():
    transport = RestTransport("http://127.0.0.1:9", timeout_sec=1)
    with pytest.raises(TransportError):
        transport.heartbeat("TOK", {})
