"""Customer waiting queue (join / call / seat / cancel)."""

from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    QueueEntryResponse,
    QueueJoin,
    QueueSeatRequest,
    SeatResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.queue_service import QueueService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/queue", tags=["queue"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(conn, action, auth, entry_id, request):
    log_audit(
        conn, action=action, user_id=auth.user_id,
        role_name=",".join(auth.roles), entity_type="queue_entry",
        entity_id=entry_id, ip_address=_ip(request),
    )


@router.post("", response_model=QueueEntryResponse, status_code=201)
def join(
    payload: QueueJoin,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> QueueEntryResponse:
    with get_connection() as conn:
        try:
            entry = QueueService(conn).join(
                customer_id=payload.customer_id, pc_id=payload.pc_id,
                priority=payload.priority, note=payload.note,
                created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _audit(conn, "QUEUE_JOIN", auth, entry["id"], request)
        return QueueEntryResponse(**entry)


@router.get("", response_model=list[QueueEntryResponse])
def list_queue(
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> list[QueueEntryResponse]:
    with get_connection() as conn:
        return [QueueEntryResponse(**e)
                for e in QueueService(conn).list()]


@router.post("/{entry_id}/call", response_model=QueueEntryResponse)
def call_entry(
    entry_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> QueueEntryResponse:
    with get_connection() as conn:
        try:
            entry = QueueService(conn).call(entry_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "QUEUE_CALL", auth, entry_id, request)
        return QueueEntryResponse(**entry)


@router.post("/{entry_id}/seat", response_model=SeatResponse)
def seat_entry(
    entry_id: str,
    payload: QueueSeatRequest,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> SeatResponse:
    with get_connection() as conn:
        try:
            result = QueueService(conn).seat(
                entry_id, pc_id=payload.pc_id,
                actor_user_id=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "QUEUE_SEAT", auth, entry_id, request)
        return SeatResponse(entry=result["entry"],
                            session=result["session"])


@router.post("/{entry_id}/cancel", response_model=QueueEntryResponse)
def cancel_entry(
    entry_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> QueueEntryResponse:
    with get_connection() as conn:
        try:
            entry = QueueService(conn).cancel(entry_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "QUEUE_CANCEL", auth, entry_id, request)
        return QueueEntryResponse(**entry)
