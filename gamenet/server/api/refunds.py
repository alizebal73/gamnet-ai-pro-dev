"""Sale refunds (money out + credit clawback)."""

from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    RefundCreate,
    RefundResponse,
    RefundResultResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.refund_service import RefundService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/sales", tags=["refunds"])


@router.post("/{sale_id}/refunds", response_model=RefundResultResponse,
             status_code=201)
def create_refund(
    sale_id: str,
    payload: RefundCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SALES_REFUND)),
) -> RefundResultResponse:
    with get_connection() as conn:
        try:
            result = RefundService(conn).refund(
                sale_id=sale_id, amount=payload.amount,
                method=payload.method, reason=payload.reason,
                created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="SALE_REFUND", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="refund",
            entity_id=result["refund"]["id"], amount=payload.amount,
            reason=f"{result['refund']['method']}: {payload.reason}",
            ip_address=request.client.host if request.client else None,
        )
        return RefundResultResponse(
            refund=RefundResponse(**result["refund"]),
            revoked_sec=result["revoked_sec"],
            clawed_balance=result["clawed_balance"],
            vips_cancelled=result["vips_cancelled"],
            refunded_total=result["refunded_total"],
        )


@router.get("/{sale_id}/refunds", response_model=list[RefundResponse])
def list_refunds(
    sale_id: str,
    auth: AuthContext = Depends(require_permission(Permission.SALES_REFUND)),
) -> list[RefundResponse]:
    with get_connection() as conn:
        try:
            refunds = RefundService(conn).list_for_sale(sale_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return [RefundResponse(**r) for r in refunds]
