from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gamenet.server.api.deps import get_current_user
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    AuthUserResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
)
from gamenet.server.services.auth_service import (
    AccountLockedError,
    AuthContext,
    AuthError,
    AuthService,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_optional_bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request) -> LoginResponse:
    with get_connection() as conn:
        try:
            result = AuthService(conn).login(
                username=payload.username,
                password=payload.password,
                ip=_client_ip(request),
            )
        except AccountLockedError as exc:
            # Login writes audit rows before raising; commit them, else the
            # context manager would roll back the security trail.
            conn.commit()
            raise HTTPException(
                status_code=423,
                detail={"message": str(exc), "locked_until": exc.locked_until},
            )
        except AuthError as exc:
            # Preserve failed-attempt counter + audit trail (see above).
            conn.commit()
            raise HTTPException(status_code=401, detail=str(exc))
        return LoginResponse(
            access_token=result["token"],
            expires_at=result["expires_at"],
            user=AuthUserResponse(**result["user"]),
        )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> None:
    # Idempotent: always 204, even without a token.
    if credentials:
        with get_connection() as conn:
            AuthService(conn).logout(
                token=credentials.credentials, ip=_client_ip(request)
            )


@router.get("/me", response_model=MeResponse)
def me(auth: AuthContext = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user=AuthUserResponse(
            id=auth.user_id,
            username=auth.username,
            display_name=auth.display_name,
            status=auth.status,
            roles=auth.roles,
        ),
        permissions=sorted(auth.permissions),
    )
