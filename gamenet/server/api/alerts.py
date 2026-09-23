"""Alert inbox + evaluation + Telegram test (P4-2)."""

from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    AlertEvaluateResponse,
    AlertListResponse,
    AlertResponse,
    TelegramTestResponse,
)
from gamenet.server.services.alert_service import AlertService
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.telegram_service import (
    TelegramError,
    TelegramService,
)
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=AlertListResponse)
def list_alerts(
    status: str | None = None,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> AlertListResponse:
    with get_connection() as conn:
        try:
            items = AlertService(conn).list_alerts(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return AlertListResponse(
            items=[AlertResponse(**a) for a in items],
            total=len(items),
        )


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: str,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> AlertResponse:
    with get_connection() as conn:
        try:
            return AlertResponse(**AlertService(conn).get(alert_id))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{alert_id}/ack", response_model=AlertResponse)
def ack_alert(
    alert_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> AlertResponse:
    with get_connection() as conn:
        try:
            alert = AlertService(conn).ack(alert_id, auth.user_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        log_audit(
            conn, action="ALERT_ACK", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="alert",
            entity_id=alert_id, ip_address=_client_ip(request),
        )
        return AlertResponse(**alert)


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
def resolve_alert(
    alert_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> AlertResponse:
    with get_connection() as conn:
        try:
            alert = AlertService(conn).resolve(alert_id, auth.user_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        log_audit(
            conn, action="ALERT_RESOLVE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="alert",
            entity_id=alert_id, ip_address=_client_ip(request),
        )
        return AlertResponse(**alert)


@router.post("/evaluate", response_model=AlertEvaluateResponse)
def evaluate_alerts(
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> AlertEvaluateResponse:
    with get_connection() as conn:
        result = AlertService(conn).evaluate()
        notified = 0
        telegram = TelegramService(conn)
        for alert in result["created"]:
            if alert["severity"] not in ("WARNING", "CRITICAL"):
                continue
            try:
                if telegram.notify_alert(alert) is not None:
                    notified += 1
            except TelegramError:
                # A broken notifier must not fail evaluation; the
                # alert itself is already stored.
                continue
        log_audit(
            conn, action="ALERT_EVALUATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="alert",
            reason=f"created={len(result['created'])} "
                   f"resolved={len(result['resolved'])}",
            ip_address=_client_ip(request),
        )
        return AlertEvaluateResponse(
            created=[AlertResponse(**a) for a in result["created"]],
            resolved=result["resolved"],
            notified=notified,
        )


@router.post("/telegram-test", response_model=TelegramTestResponse)
def telegram_test(
    auth: AuthContext = Depends(
        require_permission(Permission.SETTINGS_EDIT)),
) -> TelegramTestResponse:
    with get_connection() as conn:
        try:
            resp = TelegramService(conn).test()
        except TelegramError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        result = resp.get("result") or {}
        return TelegramTestResponse(ok=True,
                                    message_id=result.get("message_id"))
