"""Agent configuration (file + env + CLI overrides)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from gamenet import __version__


@dataclass
class AgentConfig:
    server_url: str = "http://127.0.0.1:8000"
    device_code: str = ""
    secret: str = ""
    agent_version: str = field(default_factory=lambda: __version__)
    heartbeat_interval_sec: int = 15
    request_timeout_sec: int = 10
    data_dir: str = "agent-data"
    max_backoff_sec: int = 60

    @classmethod
    def from_file(cls, path: str) -> "AgentConfig":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_env(cls) -> "AgentConfig":
        def _int(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, default))
            except (TypeError, ValueError):
                return default

        return cls(
            server_url=os.environ.get(
                "GAMENET_SERVER_URL", "http://127.0.0.1:8000"),
            device_code=os.environ.get("GAMENET_DEVICE_CODE", ""),
            secret=os.environ.get("GAMENET_DEVICE_SECRET", ""),
            heartbeat_interval_sec=_int("GAMENET_HEARTBEAT_SEC", 15),
            request_timeout_sec=_int("GAMENET_TIMEOUT_SEC", 10),
            data_dir=os.environ.get("GAMENET_DATA_DIR", "agent-data"),
            max_backoff_sec=_int("GAMENET_MAX_BACKOFF_SEC", 60),
        )

    def validate(self) -> None:
        if not self.device_code.strip():
            raise ValueError("device_code is required")
        if not self.secret:
            raise ValueError("device secret is required")
        if not self.server_url.startswith(("http://", "https://")):
            raise ValueError("server_url must start with http(s)://")
