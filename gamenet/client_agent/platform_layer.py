"""OS abstraction: everything the agent does to the local PC.

Real lockdown UIs (fullscreen overlay, kiosk) arrive with the operator
app; P2-4 executes commands through small, auditable primitives:
lock the workstation, dismiss the lock, message box, power actions.
"""

from __future__ import annotations

import shutil
import sys
from typing import Protocol


class Platform(Protocol):
    name: str

    def lock(self, reason: str) -> dict: ...
    def unlock(self, session_id: str | None) -> dict: ...
    def show_message(self, text: str) -> dict: ...
    def shutdown(self) -> dict: ...
    def restart(self) -> dict: ...
    def health(self) -> dict: ...


def disk_health() -> dict:
    try:
        usage = shutil.disk_usage(sys.executable)
        return {"disk_free_mb": usage.free // (1024 * 1024)}
    except OSError:
        return {}


class MockPlatform:
    """In-memory platform for tests: records every call."""

    name = "mock"

    def __init__(self):
        self.calls: list[tuple] = []
        self.locked = True  # agents boot locked, like production
        self.fixed_health: dict = {}

    def lock(self, reason: str) -> dict:
        self.calls.append(("lock", reason))
        self.locked = True
        return {"ok": True}

    def unlock(self, session_id: str | None) -> dict:
        self.calls.append(("unlock", session_id))
        self.locked = False
        return {"ok": True}

    def show_message(self, text: str) -> dict:
        self.calls.append(("message", text))
        return {"ok": True, "shown": True}

    def shutdown(self) -> dict:
        self.calls.append(("shutdown",))
        return {"ok": True}

    def restart(self) -> dict:
        self.calls.append(("restart",))
        return {"ok": True}

    def health(self) -> dict:
        return dict(self.fixed_health)


class WindowsPlatform:
    """Windows primitives via ctypes (no dependencies)."""

    name = "windows"

    def lock(self, reason: str) -> dict:
        import ctypes

        ok = bool(ctypes.windll.user32.LockWorkStation())
        return {"ok": ok}

    def unlock(self, session_id: str | None) -> dict:
        # A real unlock needs a credential provider; until the kiosk UI
        # ships, UNLOCK only clears the agent-side locked flag (the user
        # signs back in with their Windows account).
        return {"ok": True, "note": "manual sign-in required"}

    def show_message(self, text: str) -> dict:
        import ctypes
        from threading import Thread

        def _box() -> None:
            ctypes.windll.user32.MessageBoxW(
                None, text[:2000], "GameNet", 0x40)

        Thread(target=_box, daemon=True).start()
        return {"ok": True, "shown": True}

    def _power(self, flag: str) -> dict:
        import subprocess

        subprocess.Popen(["shutdown.exe", flag, "/t", "10"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True}

    def shutdown(self) -> dict:
        return self._power("/s")

    def restart(self) -> dict:
        return self._power("/r")

    def health(self) -> dict:
        stats = disk_health()
        try:
            import psutil  # optional, used when installed

            stats["cpu_pct"] = psutil.cpu_percent(interval=None)
            stats["mem_pct"] = psutil.virtual_memory().percent
            try:
                temps = psutil.sensors_temperatures()
            except AttributeError:
                temps = {}
            if temps:
                first = next(iter(temps.values()))[0]
                stats["temp_c"] = float(first.current)
        except ImportError:
            pass
        return stats


class PosixPlatform:
    """Best-effort Linux primitives (lock session, poweroff/reboot)."""

    name = "posix"

    def _run(self, *argv: str) -> bool:
        import subprocess

        try:
            subprocess.run(list(argv), timeout=10, check=False,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def lock(self, reason: str) -> dict:
        ok = self._run("loginctl", "lock-session")
        return {"ok": ok}

    def unlock(self, session_id: str | None) -> dict:
        return {"ok": True, "note": "manual sign-in required"}

    def show_message(self, text: str) -> dict:
        ok = self._run("notify-send", "GameNet", text[:500])
        return {"ok": ok, "shown": ok}

    def shutdown(self) -> dict:
        return {"ok": self._run("systemctl", "poweroff")}

    def restart(self) -> dict:
        return {"ok": self._run("systemctl", "reboot")}

    def health(self) -> dict:
        stats = disk_health()
        try:
            import psutil  # optional, used when installed

            stats["cpu_pct"] = psutil.cpu_percent(interval=None)
            stats["mem_pct"] = psutil.virtual_memory().percent
            try:
                temps = psutil.sensors_temperatures()
            except AttributeError:
                temps = {}
            if temps:
                first = next(iter(temps.values()))[0]
                stats["temp_c"] = float(first.current)
        except ImportError:
            pass
        return stats


def detect_platform() -> Platform:
    if sys.platform.startswith("win"):
        return WindowsPlatform()
    if sys.platform.startswith(("linux", "darwin")):
        return PosixPlatform()
    raise RuntimeError(f"Unsupported platform: {sys.platform}")
