import sqlite3

from gamenet.server.repositories.user_repository import UserRepository
from gamenet.server.security.passwords import hash_secret

MIN_PASSWORD_LEN = 8


class UserService:
    def __init__(self, conn: sqlite3.Connection):
        self._users = UserRepository(conn)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        roles: list[str],
    ) -> dict:
        username = username.strip()
        if not username:
            raise ValueError("username is required")
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        if not roles:
            raise ValueError("at least one role is required")
        for role_id in roles:
            if not self._users.role_exists(role_id):
                raise ValueError(f"unknown role: {role_id}")
        if self._users.username_exists(username):
            raise ValueError(f"username '{username}' already exists")

        user = self._users.create(
            username=username,
            password_hash=hash_secret(password),
            display_name=display_name.strip() if display_name else None,
        )
        for role_id in roles:
            self._users.assign_role(user["id"], role_id)
        user["roles"] = self._users.get_roles(user["id"])
        return user
