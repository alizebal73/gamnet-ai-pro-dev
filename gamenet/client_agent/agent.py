"""Headless client agent: heartbeat, commands, reconnect, crash recovery.

Master Spec coverage: device auth (135), heartbeat (326-328), remote
commands with ACK (121-123), reconnect with backoff (15), session sync
(21-23), no auto-continue without server validation after restart
(54), local pending-ACK queue surviving crashes (50-53).

Safety rules (all enforced here, all tested):
  - The agent boots LOCKED and only UNLOCKs on an explicit UNLOCK
    command. Session sync may LOCK (safe direction) but never unlock.
  - Every executed command is ACKed; failed ACKs are retried on the
    next heartbeat, surviving process restarts via state.json.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from gamenet.client_agent.config import AgentConfig
from gamenet.client_agent.platform_layer import Platform, detect_platform
from gamenet.client_agent.transport import (
    AgentAuthError,
    RestTransport,
    Transport,
    TransportError,
)


@dataclass
class PendingAck:
    command_id: str
    ok: bool
    result: dict = field(default_factory=dict)


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        transport: Transport | None = None,
        platform: Platform | None = None,
        sleep=time.sleep,
    ):
        self._config = config
        self._transport = transport or RestTransport(
            config.server_url, config.request_timeout_sec)
        self._platform = platform or detect_platform()
        self._sleep = sleep
        self._token: str | None = None
        self._locked = True
        self._session_id: str | None = None
        self._pending_ack: list[PendingAck] = []
        self._state_path = os.path.join(config.data_dir, "state.json")
        self._load_state()

    # -- observable state (tests + future UI) ---------------------------
    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def pending_acks(self) -> list[PendingAck]:
        return list(self._pending_ack)

    # -- main loop ------------------------------------------------------
    def run_forever(self, stop=None) -> None:
        """Beat until `stop` is set (a threading.Event) or Ctrl-C."""
        backoff = 1
        while stop is None or not stop.is_set():
            try:
                self.tick()
                backoff = 1
            except AgentAuthError:
                self._token = None  # force re-auth next tick, no sleep
                continue
            except TransportError:
                backoff = min(backoff * 2, self._config.max_backoff_sec)
                self._sleep(backoff)
                continue
            self._sleep(self._config.heartbeat_interval_sec)

    def tick(self) -> dict:
        """One heartbeat iteration. Returns a summary (used by tests)."""
        summary: dict = {"commands": [], "acked": [], "errors": []}
        if self._token is None:
            auth = self._transport.authenticate(
                self._config.device_code, self._config.secret,
                self._config.agent_version,
            )
            self._token = auth["token"]
            summary["authed"] = True
        beat = self._transport.heartbeat(self._token, {
            "session_id": self._session_id,
            "agent_version": self._config.agent_version,
            **self._platform.health(),
        })
        summary["server_time"] = beat.get("server_time")
        self._apply_session_sync(beat.get("session"), summary)
        for cmd in beat.get("commands", []):
            ok, result = self._execute(cmd)
            summary["commands"].append(
                {"id": cmd.get("id"), "type": cmd.get("type"), "ok": ok})
            self._pending_ack.append(
                PendingAck(cmd.get("id", ""), ok, result))
        self._flush_acks(summary)
        self._save_state()
        return summary

    # -- internals ------------------------------------------------------
    def _apply_session_sync(self, server_session: dict | None,
                            summary: dict) -> None:
        if server_session is None:
            if self._session_id is not None:
                # Server-side session is gone (ended/cancelled while we
                # were offline): lock, never continue.
                self._platform.lock("SESSION_GONE")
                self._locked = True
                summary["sync"] = "locked:session-gone"
            self._session_id = None
            return
        self._session_id = server_session.get("id")
        if server_session.get("status") in ("PAUSED", "AUTHORIZED") \
                and not self._locked:
            self._platform.lock(f"SESSION_{server_session.get('status')}")
            self._locked = True
            summary["sync"] = f"locked:session-{server_session.get('status')}".lower()

    def _execute(self, cmd: dict) -> tuple[bool, dict]:
        ctype = (cmd.get("type") or "").upper()
        payload = cmd.get("payload") or {}
        try:
            if ctype == "LOCK":
                result = self._platform.lock(
                    str(payload.get("reason", "LOCK")))
                self._locked = True
                return True, result
            if ctype == "UNLOCK":
                result = self._platform.unlock(payload.get("session_id"))
                self._locked = False
                return True, result
            if ctype == "MESSAGE":
                return True, self._platform.show_message(
                    str(payload.get("text", "")))
            if ctype == "SHUTDOWN":
                return True, self._platform.shutdown()
            if ctype == "RESTART":
                return True, self._platform.restart()
            if ctype == "END_SESSION":
                self._platform.lock("END_SESSION")
                self._locked = True
                self._session_id = None
                return True, {"ok": True}
            if ctype == "SYNC":
                return True, {"ok": True, "locked": self._locked}
            return False, {"ok": False,
                           "error": f"Unknown command type: {ctype}"}
        except Exception as exc:  # platform failures are reported, not raised
            return False, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _flush_acks(self, summary: dict) -> None:
        if self._token is None:
            return
        done = 0
        for ack in self._pending_ack:
            try:
                self._transport.ack(self._token, ack.command_id, ack.ok,
                                    ack.result)
            except TransportError as exc:
                summary["errors"].append(str(exc))
                break  # keep order; retry the rest next tick
            summary["acked"].append(ack.command_id)
            done += 1
        del self._pending_ack[:done]

    # -- crash recovery -------------------------------------------------
    def _load_state(self) -> None:
        try:
            with open(self._state_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return  # first boot: locked, no session, nothing pending
        self._locked = bool(data.get("locked", True))
        self._session_id = data.get("session_id")
        for item in data.get("pending_ack", []):
            self._pending_ack.append(PendingAck(
                item.get("command_id", ""), bool(item.get("ok", True)),
                item.get("result") or {}))

    def _save_state(self) -> None:
        try:
            os.makedirs(self._config.data_dir, exist_ok=True)
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({
                    "locked": self._locked,
                    "session_id": self._session_id,
                    "pending_ack": [
                        {"command_id": a.command_id, "ok": a.ok,
                         "result": a.result}
                        for a in self._pending_ack
                    ],
                }, fh)
            os.replace(tmp, self._state_path)
        except OSError:
            pass  # state is best-effort; the server stays authoritative
