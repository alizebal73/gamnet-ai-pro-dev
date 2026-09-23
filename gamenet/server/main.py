from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from gamenet import __version__
from gamenet.server.api.router import api_router
from gamenet.server.config import settings
from gamenet.server.db import get_connection, run_migrations
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.workers.recovery import startup_checks

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Mutating paths that stay available in safe mode (so admins can log in
# and turn safe mode back off).
SAFE_MODE_ALLOWLIST = {
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/admin/safe-mode",
}


class SafeModeMiddleware(BaseHTTPMiddleware):
    """Block mutating requests while safe mode is on (Master Spec 145/339)."""

    async def dispatch(self, request, call_next):
        if (
            request.method not in SAFE_METHODS
            and request.url.path not in SAFE_MODE_ALLOWLIST
            and not request.url.path.startswith("/api/v1/auth/")
        ):
            with get_connection() as conn:
                repo = SettingsRepository(conn)
                if repo.get("safe_mode", "0") == "1":
                    reason = repo.get("safe_mode_reason", "") or ""
                    return JSONResponse(
                        status_code=503,
                        content={"detail": f"Server is in safe mode. {reason}".strip()},
                    )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    report = startup_checks()
    print(f"[startup] recovery checks: {report}")
    yield


app = FastAPI(
    title="GameNet Pro Server",
    version=__version__,
    description="Game-net management server — Source of Truth",
    lifespan=lifespan,
)

app.add_middleware(SafeModeMiddleware)
app.include_router(api_router)


def main() -> None:
    uvicorn.run(
        "gamenet.server.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":
    main()
