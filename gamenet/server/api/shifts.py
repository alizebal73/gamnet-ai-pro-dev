"""Operator shifts + cash drawer endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    CashMovementRequest,
    CashMovementResponse,
    ShiftCloseRequest,
    ShiftOpenRequest,
    ShiftResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.shift_service import ShiftService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/shifts", tags=["shifts"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/open", response_model=ShiftResponse, status_code=201)
def open_shift(
    payload: ShiftOpenRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SHIFT_MANAGE)),
) -> ShiftResponse:
    with get_connection() as conn:
        try:
            shift = ShiftService(conn).open(
                opened_by=auth.user_id,
                opening_float=payload.opening_float,
            )
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="SHIFT_OPEN", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="shift",
            entity_id=shift["id"], amount=payload.opening_float,
            ip_address=_ip(request),
        )
        return ShiftResponse(**shift)


@router.get("/current", response_model=ShiftResponse)
def current_shift(
    auth: AuthContext = Depends(require_permission(Permission.SHIFT_MANAGE)),
) -> ShiftResponse:
    with get_connection() as conn:
        try:
            return ShiftResponse(**ShiftService(conn).current())
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.post("/current/close", response_model=ShiftResponse)
def close_shift(
    payload: ShiftCloseRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SHIFT_MANAGE)),
) -> ShiftResponse:
    with get_connection() as conn:
        try:
            shift = ShiftService(conn).close(
                closed_by=auth.user_id, counted_cash=payload.counted_cash,
                note=payload.note,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="SHIFT_CLOSE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="shift",
            entity_id=shift["id"], amount=shift["variance"],
            reason=shift["note"], ip_address=_ip(request),
        )
        return ShiftResponse(**shift)


@router.post("/current/movements", response_model=CashMovementResponse,
             status_code=201)
def add_movement(
    payload: CashMovementRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SHIFT_MANAGE)),
) -> CashMovementResponse:
    with get_connection() as conn:
        try:
            movement = ShiftService(conn).add_movement(
                kind=payload.kind, amount=payload.amount,
                reason=payload.reason, created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="CASH_MOVEMENT", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="cash_movement",
            entity_id=movement["id"], amount=payload.amount,
            reason=f"{payload.kind}: {payload.reason}",
            ip_address=_ip(request),
        )
        return CashMovementResponse(**movement)


@router.get("", response_model=list[ShiftResponse])
def shift_history(
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(require_permission(Permission.SHIFT_MANAGE)),
) -> list[ShiftResponse]:
    with get_connection() as conn:
        return [ShiftResponse(**s)
                for s in ShiftService(conn).history(limit)]


@router.get("/{shift_id}", response_model=ShiftResponse)
def shift_detail(
    shift_id: str,
    auth: AuthContext = Depends(require_permission(Permission.SHIFT_MANAGE)),
) -> ShiftResponse:
    with get_connection() as conn:
        try:
            return ShiftResponse(**ShiftService(conn).detail(shift_id))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
