"""PC reservations (book / cancel / no-show / seat)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    ReservationCancel,
    ReservationCreate,
    ReservationResponse,
    SeatResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.reservation_service import ReservationService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/reservations", tags=["reservations"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(conn, action, auth, res_id, request, reason=None):
    log_audit(
        conn, action=action, user_id=auth.user_id,
        role_name=",".join(auth.roles), entity_type="reservation",
        entity_id=res_id, reason=reason, ip_address=_ip(request),
    )


@router.post("", response_model=ReservationResponse, status_code=201)
def book(
    payload: ReservationCreate,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> ReservationResponse:
    with get_connection() as conn:
        try:
            res = ReservationService(conn).book(
                customer_id=payload.customer_id, pc_id=payload.pc_id,
                starts_at=payload.starts_at, ends_at=payload.ends_at,
                note=payload.note, created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _audit(conn, "RESERVATION_BOOK", auth, res["id"], request)
        return ReservationResponse(**res)


@router.get("", response_model=list[ReservationResponse])
def list_reservations(
    pc_id: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> list[ReservationResponse]:
    with get_connection() as conn:
        items = ReservationService(conn).list(
            pc_id=pc_id, customer_id=customer_id, status=status,
            frm=frm, to=to,
        )
        return [ReservationResponse(**r) for r in items]


@router.get("/{res_id}", response_model=ReservationResponse)
def get_reservation(
    res_id: str,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> ReservationResponse:
    with get_connection() as conn:
        try:
            return ReservationResponse(
                **ReservationService(conn).get(res_id))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{res_id}/cancel", response_model=ReservationResponse)
def cancel_reservation(
    res_id: str,
    payload: ReservationCancel,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> ReservationResponse:
    with get_connection() as conn:
        try:
            res = ReservationService(conn).cancel(
                res_id, reason=payload.reason,
                actor_user_id=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _audit(conn, "RESERVATION_CANCEL", auth, res_id, request,
               reason=payload.reason)
        return ReservationResponse(**res)


@router.post("/{res_id}/no-show", response_model=ReservationResponse)
def no_show(
    res_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> ReservationResponse:
    with get_connection() as conn:
        try:
            res = ReservationService(conn).no_show(res_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "RESERVATION_NO_SHOW", auth, res_id, request)
        return ReservationResponse(**res)


@router.post("/{res_id}/seat", response_model=SeatResponse)
def seat(
    res_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> SeatResponse:
    with get_connection() as conn:
        try:
            result = ReservationService(conn).seat(
                res_id, actor_user_id=auth.user_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "RESERVATION_SEAT", auth, res_id, request)
        return SeatResponse(
            reservation=ReservationResponse(**result["reservation"]),
            session=result["session"],
        )
