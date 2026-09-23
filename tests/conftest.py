import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Use isolated test database before app imports settings-dependent modules
_test_db = Path(__file__).parent / "_test_gamenet.db"
if _test_db.exists():
    _test_db.unlink()

os.environ["DATABASE_PATH"] = str(_test_db)
os.environ["APP_ENV"] = "test"

from gamenet.server.db import get_connection, run_migrations  # noqa: E402
from gamenet.server.main import app  # noqa: E402
from gamenet.server.services.auth_service import AuthService  # noqa: E402
from gamenet.server.services.user_service import UserService  # noqa: E402
from gamenet.shared.enums import RoleName  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    run_migrations()
    yield
    if _test_db.exists():
        _test_db.unlink(missing_ok=True)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _make_user(username: str, password: str, roles: list[str]) -> dict:
    with get_connection() as conn:
        return UserService(conn).create_user(
            username=username, password=password, roles=roles
        )


def _login(username: str, password: str) -> str:
    with get_connection() as conn:
        return AuthService(conn).login(username=username, password=password)["token"]


@pytest.fixture
def owner_headers() -> dict:
    username = f"owner_{uuid.uuid4().hex[:8]}"
    _make_user(username, "owner-pass-123", [RoleName.OWNER.value])
    return {"Authorization": f"Bearer {_login(username, 'owner-pass-123')}"}


@pytest.fixture
def make_user_with_token():
    """Factory: role -> auth headers. Creates a fresh user and logs in."""

    def _factory(role: str, password: str = "test-pass-123") -> dict:
        username = f"u_{uuid.uuid4().hex[:8]}"
        _make_user(username, password, [role])
        return {"Authorization": f"Bearer {_login(username, password)}"}

    return _factory
