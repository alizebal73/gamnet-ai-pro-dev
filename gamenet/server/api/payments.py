from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.api.sales import _payment_to_response
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import PaymentListResponse, PaymentResponse
from gamenet.server.repositories.payment_repository import PaymentRepository
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.payment_service import PaymentService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/payments", tags=["payments"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/unknown-queue", response_model=PaymentListResponse)
def unknown_queue(
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> PaymentListResponse:
    with get_connection() as conn:
        rows = PaymentService(conn).unknown_queue()
        items = [_payment_to_response(r) for r in rows]
        return PaymentListResponse(items=items, total=len(items))


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: str,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> PaymentResponse:
    with get_connection() as conn:
        row = PaymentRepository(conn).get(payment_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        return _payment_to_response(row)


@router.post("/{payment_id}/reconcile", response_model=PaymentResponse)
def reconcile_payment(
    payment_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> PaymentResponse:
    with get_connection() as conn:
        try:
            row = PaymentService(conn).reconcile(payment_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        log_audit(
            conn, action="PAYMENT_RECONCILE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="payment",
            entity_id=payment_id, new_value=row["status"],
            ip_address=_client_ip(request),
        )
        return _payment_to_response(row)
