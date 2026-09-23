from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    SessionAuthorize,
    SessionConsumptionResponse,
    SessionCreate,
    SessionDetailResponse,
    SessionEnd,
    SessionEventResponse,
    SessionListResponse,
    SessionPause,
    SessionResponse,
    SessionTransfer,
)
from gamenet.server.repositories.session_repository import SessionRepository
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.session_service import SessionService
from gamenet.shared.enums import Permission, SessionStatus

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _to_detail(detail: dict) -> SessionDetailResponse:
    return SessionDetailResponse(
        **{k: detail[k] for k in SessionResponse.model_fields},
        events=[SessionEventResponse(**e) for e in detail["events"]],
        consumptions=[
            SessionConsumptionResponse(**c) for c in detail["consumptions"]
        ],
        customer_remaining_sec=detail["customer_remaining_sec"],
        expected_ends_at=detail.get("expected_ends_at"),
        expected_remaining_sec=detail.get("expected_remaining_sec"),
    )


def _audit(
    conn, request: Request, auth: AuthContext, action: str, detail: dict,
    reason: str | None = None,
) -> None:
    log_audit(
        conn, action=action, user_id=auth.user_id,
        role_name=",".join(auth.roles), entity_type="session",
        entity_id=detail["id"], pc_id=detail["pc_id"],
        customer_id=detail["customer_id"], reason=reason,
        ip_address=_client_ip(request),
    )


@router.post("", response_model=SessionDetailResponse, status_code=201)
def create_session(
    payload: SessionCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    with get_connection() as conn:
        try:
            detail = SessionService(conn).create(
                customer_id=payload.customer_id, pc_id=payload.pc_id,
                created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _audit(conn, request, auth, "SESSION_CREATE", detail)
        return _to_detail(detail)


@router.get("", response_model=SessionListResponse)
def list_sessions(
    customer_id: str | None = Query(default=None),
    pc_id: str | None = Query(default=None),
    status: SessionStatus | None = Query(default=None),
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionListResponse:
    with get_connection() as conn:
        rows = SessionRepository(conn).list_sessions(
            customer_id=customer_id, pc_id=pc_id,
            status=status.value if status else None,
        )
        items = [
            SessionResponse(**{k: r[k] for k in SessionResponse.model_fields})
            for r in rows
        ]
        return SessionListResponse(items=items, total=len(items))


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    with get_connection() as conn:
        try:
            detail = SessionService(conn).detail(session_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return _to_detail(detail)


def _transition(
    request: Request,
    auth: AuthContext,
    action: str,
    session_id: str,
    fn_name: str,
    **kwargs,
) -> SessionDetailResponse:
    with get_connection() as conn:
        service = SessionService(conn)
        try:
            detail = getattr(service, fn_name)(
                session_id, actor_user_id=auth.user_id, **kwargs
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _audit(conn, request, auth, action, detail,
               reason=kwargs.get("reason"))
        return _to_detail(detail)


@router.post("/{session_id}/authorize", response_model=SessionDetailResponse)
def authorize_session(
    session_id: str,
    payload: SessionAuthorize,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_AUTHORIZE", session_id,
                       "authorize", pc_id=payload.pc_id)


@router.post("/{session_id}/start", response_model=SessionDetailResponse)
def start_session(
    session_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_START", session_id, "start")


@router.post("/{session_id}/pause", response_model=SessionDetailResponse)
def pause_session(
    session_id: str,
    payload: SessionPause,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_PAUSE", session_id, "pause",
                       reason=payload.reason)


@router.post("/{session_id}/resume", response_model=SessionDetailResponse)
def resume_session(
    session_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_RESUME", session_id, "resume")


@router.post("/{session_id}/end", response_model=SessionDetailResponse)
def end_session(
    session_id: str,
    payload: SessionEnd,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_END", session_id, "end",
                       reason=payload.reason)


@router.post("/{session_id}/cancel", response_model=SessionDetailResponse)
def cancel_session(
    session_id: str,
    payload: SessionEnd,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_CANCEL", session_id, "cancel",
                       reason=payload.reason)


@router.post("/{session_id}/extend", response_model=SessionDetailResponse)
def extend_session(
    session_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
    note: str | None = None,
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_EXTEND", session_id,
                       "extend", note=note)


@router.post("/{session_id}/transfer", response_model=SessionDetailResponse)
def transfer_session(
    session_id: str,
    payload: SessionTransfer,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SESSION_OPERATE)),
) -> SessionDetailResponse:
    return _transition(request, auth, "SESSION_TRANSFER", session_id,
                       "transfer", new_pc_id=payload.new_pc_id,
                       reason=payload.reason)
