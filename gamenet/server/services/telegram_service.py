"""Telegram notifications (P4-2, stdlib only).

Configured via the `telegram_bot_token` / `telegram_chat_id` settings.
`http_post` is a module-level hook so tests can stub the provider call
without touching the network.
"""

import json
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable

from gamenet.server.repositories.settings_repository import (
    SettingsRepository,
)


class TelegramError(Exception):
    pass


def _default_http_post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except OSError:
            detail = exc.reason
        raise TelegramError(f"Telegram API HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, OSError) as exc:
        raise TelegramError(f"Cannot reach Telegram: {exc}")


http_post: Callable[[str, dict], dict] = _default_http_post


class TelegramService:
    def __init__(self, conn: sqlite3.Connection):
        self._settings = SettingsRepository(conn)

    def is_configured(self) -> bool:
        token = (self._settings.get("telegram_bot_token") or "").strip()
        chat = (self._settings.get("telegram_chat_id") or "").strip()
        return bool(token and chat)

    def send(self, text: str) -> dict:
        token = (self._settings.get("telegram_bot_token") or "").strip()
        chat_id = (self._settings.get("telegram_chat_id") or "").strip()
        if not token or not chat_id:
            raise TelegramError("Telegram is not configured")
        return http_post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat_id, "text": text},
        )

    def notify_alert(self, alert: dict) -> dict | None:
        """Send an alert notification; None when Telegram is off."""
        if not self.is_configured():
            return None
        lines = [f"[{alert['severity']}] {alert['title']}"]
        if alert.get("detail"):
            lines.append(alert["detail"])
        return self.send("\n".join(lines))

    def test(self) -> dict:
        return self.send("GameNet test message: Telegram alerts are on.")
