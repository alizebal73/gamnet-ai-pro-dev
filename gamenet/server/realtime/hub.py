"""WebSocket connection hub: live server -> agent push (Master Spec 326).

One socket per PC (a second connect replaces a stale one). `push_sync` can
be called from any thread (FastAPI sync routes run in a threadpool): it
schedules the send on the socket's event loop and waits briefly.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

from starlette.websockets import WebSocket


@dataclass
class SocketEntry:
    pc_id: str
    socket: WebSocket
    loop: asyncio.AbstractEventLoop
    agent_version: str | None = None
    connected_at: float = 0.0


_lock = threading.Lock()
_sockets: dict[str, SocketEntry] = {}


def connect(pc_id: str, socket: WebSocket, agent_version: str | None,
            now_ts: float) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    with _lock:
        _sockets[pc_id] = SocketEntry(
            pc_id=pc_id, socket=socket, loop=loop,
            agent_version=agent_version, connected_at=now_ts,
        )


def disconnect(pc_id: str, socket: WebSocket) -> None:
    with _lock:
        entry = _sockets.get(pc_id)
        if entry is not None and entry.socket is socket:
            del _sockets[pc_id]


def is_connected(pc_id: str) -> bool:
    with _lock:
        return pc_id in _sockets


def connected_pcs() -> list[str]:
    with _lock:
        return list(_sockets.keys())


def push_sync(pc_id: str, message: dict,
              timeout: float = 5.0) -> bool:
    """Send a JSON message to a connected PC. Returns False if offline."""
    with _lock:
        entry = _sockets.get(pc_id)
    if entry is None:
        return False
    try:
        fut = asyncio.run_coroutine_threadsafe(
            entry.socket.send_json(message), entry.loop
        )
        fut.result(timeout)
        return True
    except Exception:
        return False


def reset() -> None:
    """Test helper: drop all socket registrations (sockets stay open)."""
    with _lock:
        _sockets.clear()
