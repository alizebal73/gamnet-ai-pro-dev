from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    AuditListResponse,
    AuditResponse,
    AuditVerifyResponse,
    ReconcileResponse,
    SafeModeRequest,
    SafeModeResponse,
)
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.audit_service import log_audit, verify_audit_chain
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.workers.reconciliation import latest_run, run_reconciliation
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/admin", tags=["admin"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/safe-mode", response_model=SafeModeResponse)
def set_safe_mode(
    payload: SafeModeRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> SafeModeResponse:
    with get_connection() as conn:
        repo = SettingsRepository(conn)
        repo.set("safe_mode", "1" if payload.enabled else "0")
        reason = (payload.reason or "").strip()
        repo.set("safe_mode_reason", reason)
        log_audit(
            conn, action="SAFE_MODE", user_id=auth.user_id,
            role_name=",".join(auth.roles),
            new_value="ON" if payload.enabled else "OFF",
            reason=reason or None, ip_address=_client_ip(request),
        )
        return SafeModeResponse(safe_mode=payload.enabled, reason=reason)


@router.get("/audit", response_model=AuditListResponse)
def list_audit(
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)
    ),
) -> AuditListResponse:
    with get_connection() as conn:
        sql = "SELECT * FROM audit_logs WHERE 1 = 1"
        params: list = []
        if action:
            sql += " AND action = ?"
            params.append(action)
        if entity_type:
            sql += " AND entity_type = ?"
            params.append(entity_type)
        if customer_id:
            sql += " AND customer_id = ?"
            params.append(customer_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        fields = set(AuditResponse.model_fields)
        items = [
            AuditResponse(**{k: dict(r)[k] for k in fields}) for r in rows
        ]
        return AuditListResponse(items=items, total=len(items))


@router.get("/audit-verify", response_model=AuditVerifyResponse)
def audit_verify(
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)
    ),
) -> AuditVerifyResponse:
    with get_connection() as conn:
        return AuditVerifyResponse(**verify_audit_chain(conn))


@router.post("/reconcile", response_model=ReconcileResponse)
def run_reconcile(
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)
    ),
) -> ReconcileResponse:
    with get_connection() as conn:
        run = run_reconciliation(conn, triggered_by=auth.user_id)
        log_audit(
            conn, action="RECONCILE_RUN", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="reconciliation",
            entity_id=run["id"], new_value=run["status"],
            ip_address=_client_ip(request),
        )
        return ReconcileResponse(**run)


@router.get("/reconcile/latest", response_model=ReconcileResponse)
def reconcile_latest(
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_FINANCIAL)
    ),
) -> ReconcileResponse:
    with get_connection() as conn:
        run = latest_run(conn)
        if run is None:
            raise HTTPException(
                status_code=404, detail="No reconciliation run yet"
            )
        return ReconcileResponse(**run)
