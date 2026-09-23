"""Auth dependencies: every protected route uses these (Master Spec 92-94, 194)."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gamenet.server.db import get_connection
from gamenet.server.services.auth_service import AuthContext, AuthError, AuthService

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    with get_connection() as conn:
        try:
            return AuthService(conn).authenticate(token=credentials.credentials)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


def require_permission(permission: str):
    """Dependency factory enforcing a single server-side permission."""

    def checker(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
        if not auth.has_permission(permission):
            raise HTTPException(
                status_code=403, detail=f"Missing permission: {permission}"
            )
        return auth

    return checker
