"""Customer authentication: PIN login for the client UI (P3-5, Spec 139).

Separate from operator auth AND device auth: short-lived opaque tokens,
per-customer attempt counting with temporary lockout, everything audited.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from gamenet.server.db import to_utc_iso, utc_now_iso
from gamenet.server.repositories.customer_auth_repository import (
    CustomerAuthRepository,
)
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.security.passwords import verify_secret
from gamenet.server.security.tokens import generate_token, hash_token
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.errors import NotFound


class CustomerAuthError(Exception):
    pass


class CustomerLockedError(CustomerAuthError):
    def __init__(self, locked_until: str):
        super().__init__("Account is temporarily locked")
        self.locked_until = locked_until


@dataclass
class CustomerContext:
    customer_id: str
    customer: dict = field(default_factory=dict)


class CustomerAuthService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._auth = CustomerAuthRepository(conn)
        self._settings = SettingsRepository(conn)

    def login(self, *, identifier: str, pin: str,
              ip: str | None) -> dict:
        now = utc_now_iso()
        customer = self._auth.find_customer(identifier)
        if customer is None or customer["status"] != "ACTIVE":
            raise CustomerAuthError("Invalid credentials")
        row = self._auth.get_auth(customer["id"])
        if row is None:
            raise CustomerAuthError("Invalid credentials")
        if row["locked_until"] and row["locked_until"] > now:
            raise CustomerLockedError(row["locked_until"])
        if not verify_secret(pin or "", row["pin_hash"]):
            max_attempts = self._settings.get_int(
                "customer_max_attempts", 5)
            attempts = self._auth.record_failure(
                customer["id"], now, None)
            locked_until = None
            if attempts >= max_attempts:
                minutes = self._settings.get_int(
                    "customer_lockout_min", 15)
                locked_until = to_utc_iso(
                    datetime.now(timezone.utc)
                    + timedelta(minutes=minutes))
                self._auth.record_failure(
                    customer["id"], now, locked_until)
            log_audit(
                self._conn, action="LOGIN_FAILED", entity_type="customer",
                entity_id=customer["id"],
                reason=f"{attempts} failed PIN attempts", ip_address=ip,
            )
            if locked_until:
                raise CustomerLockedError(locked_until)
            raise CustomerAuthError("Invalid credentials")
        self._auth.reset_attempts(customer["id"], now)
        ttl = self._settings.get_int("customer_token_ttl_hours", 12)
        token = generate_token()
        expires_at = to_utc_iso(datetime.now(timezone.utc)
                                + timedelta(hours=ttl))
        self._auth.create_session(hash_token(token), customer["id"],
                                  now, expires_at, ip)
        log_audit(
            self._conn, action="LOGIN", entity_type="customer",
            entity_id=customer["id"], ip_address=ip,
        )
        return {"customer": _public_customer(customer), "token": token,
                "expires_at": expires_at}

    def authenticate(self, token: str) -> CustomerContext:
        row = self._auth.find_session(hash_token(token), utc_now_iso())
        if row is None:
            raise CustomerAuthError("Invalid or expired token")
        customer = self._auth.find_customer(row["customer_id"])
        if customer is None or customer["status"] != "ACTIVE":
            raise CustomerAuthError("Invalid or expired token")
        return CustomerContext(customer_id=customer["id"],
                               customer=_public_customer(customer))

    def logout(self, token: str, ip: str | None) -> None:
        row = self._auth.find_session(hash_token(token), utc_now_iso())
        if row is None:
            raise NotFound("Session not found")
        self._auth.revoke_session(hash_token(token), utc_now_iso())
        log_audit(
            self._conn, action="LOGOUT", entity_type="customer",
            entity_id=row["customer_id"], ip_address=ip,
        )


def _public_customer(customer: dict) -> dict:
    return {
        "id": customer["id"],
        "customer_number": customer["customer_number"],
        "name": customer["name"],
        "gaming_name": customer.get("gaming_name"),
        "status": customer["status"],
    }
