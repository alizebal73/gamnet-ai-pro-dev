import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from gamenet.server.config import settings
from gamenet.server.db import to_utc_iso, utc_now_iso
from gamenet.server.repositories.auth_session_repository import AuthSessionRepository
from gamenet.server.repositories.user_repository import UserRepository
from gamenet.server.security.passwords import verify_secret
from gamenet.server.security.tokens import generate_token, hash_token
from gamenet.server.services.audit_service import log_audit


class AuthError(Exception):
    """Invalid credentials or token (maps to HTTP 401)."""


class AccountLockedError(AuthError):
    def __init__(self, locked_until: str):
        super().__init__("Account is temporarily locked")
        self.locked_until = locked_until


@dataclass
class AuthContext:
    user_id: str
    username: str
    display_name: str | None
    status: str
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


class AuthService:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._users = UserRepository(conn)
        self._sessions = AuthSessionRepository(conn)

    def login(self, *, username: str, password: str, ip: str | None = None) -> dict:
        username = username.strip()
        user = self._users.get_by_username(username)
        if user is None or user["status"] != "ACTIVE":
            # Generic message: do not reveal whether the username exists.
            log_audit(
                self._conn, action="LOGIN_FAILED",
                reason=f"unknown or inactive user '{username}'", ip_address=ip,
            )
            raise AuthError("Invalid username or password")

        now = utc_now_iso()
        if user["locked_until"] and user["locked_until"] > now:
            raise AccountLockedError(user["locked_until"])

        if not verify_secret(password, user["password_hash"]):
            attempts = self._users.increment_failed_attempts(user["id"])
            if attempts >= settings.login_max_attempts:
                locked_until = to_utc_iso(
                    datetime.now(UTC) + timedelta(minutes=settings.login_lockout_minutes)
                )
                self._users.lock_until(user["id"], locked_until)
                log_audit(
                    self._conn, action="ACCOUNT_LOCKED", user_id=user["id"],
                    reason=f"{attempts} failed login attempts", ip_address=ip,
                )
            else:
                log_audit(self._conn, action="LOGIN_FAILED", user_id=user["id"], ip_address=ip)
            raise AuthError("Invalid username or password")

        self._users.reset_failed_attempts(user["id"])
        token = generate_token()
        expires_at = to_utc_iso(
            datetime.now(UTC) + timedelta(hours=settings.auth_token_ttl_hours)
        )
        self._sessions.create(
            token_hash=hash_token(token), user_id=user["id"],
            expires_at=expires_at, created_ip=ip,
        )
        roles = self._users.get_roles(user["id"])
        log_audit(
            self._conn, action="LOGIN", user_id=user["id"],
            role_name=",".join(roles), ip_address=ip,
        )
        return {
            "token": token,
            "expires_at": expires_at,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "status": user["status"],
                "roles": roles,
            },
        }

    def logout(self, *, token: str, ip: str | None = None) -> None:
        session = self._sessions.get_valid(hash_token(token), utc_now_iso())
        self._sessions.revoke(hash_token(token))
        if session:
            log_audit(self._conn, action="LOGOUT", user_id=session["user_id"], ip_address=ip)

    def authenticate(self, *, token: str) -> AuthContext:
        session = self._sessions.get_valid(hash_token(token), utc_now_iso())
        if session is None:
            raise AuthError("Invalid or expired token")
        user = self._users.get_by_id(session["user_id"])
        if user is None or user["status"] != "ACTIVE":
            raise AuthError("Invalid or expired token")
        return AuthContext(
            user_id=user["id"],
            username=user["username"],
            display_name=user["display_name"],
            status=user["status"],
            roles=self._users.get_roles(user["id"]),
            permissions=set(self._users.get_permissions(user["id"])),
        )
