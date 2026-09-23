"""Server transport: stdlib-only REST client for the agent channel.

Deliberately no third-party dependencies (no httpx/requests): the agent
must install trivially on gaming PCs. A WebSocket transport can implement
the same three methods later; the Agent only talks to this interface.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol


class TransportError(Exception):
    """Network failure, timeout, or unexpected server response."""


class AgentAuthError(TransportError):
    """Server rejected the credentials/token (HTTP 401)."""


class Transport(Protocol):
    def authenticate(self, device_code: str, secret: str,
                     agent_version: str) -> dict: ...
    def heartbeat(self, token: str, payload: dict) -> dict: ...
    def ack(self, token: str, command_id: str, ok: bool,
            result: dict | None) -> dict: ...


class RestTransport:
    def __init__(self, server_url: str, timeout_sec: int = 10):
        self._base = server_url.rstrip("/")
        self._timeout = timeout_sec

    def _post(self, path: str, body: dict,
              token: str | None = None) -> dict:
        req = urllib.request.Request(
            self._base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise AgentAuthError("Server rejected credentials/token")
            raise TransportError(f"HTTP {exc.code} on {path}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"{path} unreachable: {exc}")
        except ValueError as exc:
            raise TransportError(f"Bad JSON from {path}: {exc}")

    def authenticate(self, device_code: str, secret: str,
                     agent_version: str) -> dict:
        return self._post("/api/v1/agent/auth", {
            "device_code": device_code, "secret": secret,
            "agent_version": agent_version,
        })

    def heartbeat(self, token: str, payload: dict) -> dict:
        return self._post("/api/v1/agent/heartbeat", payload, token)

    def ack(self, token: str, command_id: str, ok: bool,
            result: dict | None) -> dict:
        return self._post(f"/api/v1/agent/commands/{command_id}/ack",
                          {"ok": ok, "result": result or {}}, token)
