from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    BalanceAdjust,
    BalanceLedgerEntry,
    BalanceLedgerResponse,
    BalanceResponse,
    CreditSummaryResponse,
    EntitlementResponse,
)
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.balance_service import BalanceService
from gamenet.server.services.credit_service import CreditService
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/customers/{customer_id}", tags=["credit"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _ent(row: dict) -> EntitlementResponse:
    return EntitlementResponse(
        id=row["id"], customer_id=row["customer_id"], kind=row["kind"],
        status=row["status"], effective_status=row.get("effective_status"),
        granted_sec=row["granted_sec"], consumed_sec=row["consumed_sec"],
        remaining_sec=row.get("remaining_sec"), starts_at=row["starts_at"],
        expires_at=row["expires_at"], discount_pct=row["discount_pct"],
        sale_id=row["sale_id"], sale_item_id=row["sale_item_id"],
        ref_id=row["ref_id"], created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/credit", response_model=CreditSummaryResponse)
def get_credit(
    customer_id: str,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> CreditSummaryResponse:
    with get_connection() as conn:
        try:
            summary = CreditService(conn).credit_summary(customer_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        vip = summary["active_vip"]
        return CreditSummaryResponse(
            customer_id=summary["customer_id"],
            total_remaining_sec=summary["total_remaining_sec"],
            active_vip=_ent(vip) if vip else None,
            entitlements=[_ent(e) for e in summary["entitlements"]],
        )


@router.post("/credit/refresh")
def refresh_credit(
    customer_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> dict:
    """Persist due VIP expirations/activations (normally done lazily)."""
    with get_connection() as conn:
        result = CreditService(conn).refresh_vip_states(customer_id)
        log_audit(
            conn, action="VIP_REFRESH", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="customer",
            entity_id=customer_id, customer_id=customer_id,
            new_value=str(result), ip_address=_client_ip(request),
        )
        return result


@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    customer_id: str,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> BalanceResponse:
    with get_connection() as conn:
        try:
            balance = BalanceService(conn).balance_of(customer_id)
            unit = SettingsRepository(conn).get("base_currency_unit", "RIAL")
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return BalanceResponse(
            customer_id=customer_id, balance=balance, currency_unit=unit or "RIAL"
        )


@router.get("/balance-ledger", response_model=BalanceLedgerResponse)
def get_balance_ledger(
    customer_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> BalanceLedgerResponse:
    with get_connection() as conn:
        try:
            rows = BalanceService(conn).ledger(customer_id, limit=limit)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        items = [BalanceLedgerEntry(**r) for r in rows]
        return BalanceLedgerResponse(items=items, total=len(items))


@router.post("/balance-adjust", response_model=BalanceLedgerEntry, status_code=201)
def adjust_balance(
    customer_id: str,
    payload: BalanceAdjust,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.CUSTOMER_EDIT_BALANCE)
    ),
) -> BalanceLedgerEntry:
    with get_connection() as conn:
        try:
            entry = BalanceService(conn).adjust(
                customer_id=customer_id, amount=payload.amount,
                reason=payload.reason, created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        log_audit(
            conn, action="BALANCE_ADJUST", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="customer",
            entity_id=customer_id, customer_id=customer_id,
            amount=payload.amount, reason=payload.reason,
            ip_address=_client_ip(request),
        )
        return BalanceLedgerEntry(**entry)
