"""Customer authentication: PIN login for the client UI (Spec 139)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    CustomerLogin,
    CustomerLoginResponse,
    CustomerMeResponse,
)
from gamenet.server.services.balance_service import BalanceService
from gamenet.server.services.credit_service import CreditService
from gamenet.server.services.customer_auth_service import (
    CustomerAuthError,
    CustomerAuthService,
    CustomerContext,
    CustomerLockedError,
)
from gamenet.server.services.errors import NotFound

router = APIRouter(prefix="/customers", tags=["customer-auth"])

_bearer = HTTPBearer(auto_error=False)


def get_customer_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CustomerContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    with get_connection() as conn:
        try:
            return CustomerAuthService(conn).authenticate(
                credentials.credentials)
        except CustomerAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))


@router.post("/login", response_model=CustomerLoginResponse)
def customer_login(payload: CustomerLogin, request: Request):
    with get_connection() as conn:
        try:
            result = CustomerAuthService(conn).login(
                identifier=payload.identifier, pin=payload.pin,
                ip=request.client.host if request.client else None,
            )
        except CustomerLockedError as exc:
            # Login writes the counter + audit rows before raising;
            # commit them, else the context manager would roll back
            # the security trail (same as operator login).
            conn.commit()
            raise HTTPException(status_code=423, detail={
                "message": str(exc), "locked_until": exc.locked_until,
            })
        except CustomerAuthError as exc:
            conn.commit()
            raise HTTPException(status_code=401, detail=str(exc))
        return CustomerLoginResponse(
            customer=result["customer"], token=result["token"],
            expires_at=result["expires_at"],
        )


@router.post("/logout")
def customer_logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    with get_connection() as conn:
        try:
            CustomerAuthService(conn).logout(
                credentials.credentials,
                request.client.host if request.client else None,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"ok": True}


@router.get("/me", response_model=CustomerMeResponse)
def customer_me(
    ctx: CustomerContext = Depends(get_customer_context),
) -> CustomerMeResponse:
    with get_connection() as conn:
        balance = BalanceService(conn).balance_of(ctx.customer_id)
        credit = CreditService(conn)
        return CustomerMeResponse(
            customer=ctx.customer, balance=balance,
            remaining_sec=credit.remaining_sec(ctx.customer_id),
            active_vip=credit.active_vip(ctx.customer_id),
        )
