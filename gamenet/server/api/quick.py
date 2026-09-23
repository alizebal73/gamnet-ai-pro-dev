"""One-tap operator flows: quick customer + quick sale (P3-5)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from gamenet.server.api.deps import require_permission
from gamenet.server.api.sales import _detail_to_response
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    QuickCustomerCreate,
    QuickSaleCreate,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import (
    InvalidState,
    NotFound,
    PermissionDenied,
)
from gamenet.server.services.idempotency import (
    IdempotencyConflict,
    idempotent_call,
)
from gamenet.server.services.quick_service import QuickService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/quick", tags=["quick"])


class _ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _request_id(request: Request) -> str | None:
    request_id = request.headers.get("x-request-id")
    if request_id is None:
        return None
    request_id = request_id.strip()
    if not 1 <= len(request_id) <= 64:
        raise HTTPException(
            status_code=422, detail="Invalid X-Request-ID (1-64 chars)."
        )
    return request_id


@router.post("/customer", status_code=201)
def quick_customer(
    payload: QuickCustomerCreate,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.CUSTOMER_CREATE)),
    _sales: AuthContext = Depends(
        require_permission(Permission.SALES_CREATE)),
):
    request_id = _request_id(request)
    with get_connection() as conn:
        service = QuickService(conn)

        def _do():
            try:
                result = service.quick_customer(
                    name=payload.name, pin=payload.pin,
                    mobile=payload.mobile,
                    gaming_name=payload.gaming_name,
                    recharge_amount=payload.recharge_amount,
                    auth=auth,
                )
            except NotFound as exc:
                raise _ApiError(404, str(exc))
            except InvalidState as exc:
                raise _ApiError(409, str(exc))
            except PermissionDenied as exc:
                raise _ApiError(403, str(exc))
            except ValueError as exc:
                raise _ApiError(422, str(exc))
            sale = result["sale"]
            log_audit(
                conn, action="QUICK_CUSTOMER", user_id=auth.user_id,
                role_name=",".join(auth.roles), entity_type="customer",
                entity_id=result["customer"]["id"],
                customer_id=result["customer"]["id"],
                ip_address=_client_ip(request),
            )
            return 201, {
                "customer": result["customer"],
                "sale": _detail_to_response(sale).model_dump(
                    mode="json") if sale else None,
            }

        try:
            if not request_id:
                status_code, body = _do()
            else:
                result = idempotent_call(
                    conn, request_id=request_id,
                    action="quick.customer",
                    payload=payload.model_dump(mode="json"), fn=_do,
                )
                status_code, body = result.status_code, result.body
        except _ApiError as exc:
            raise HTTPException(status_code=exc.status,
                                detail=exc.detail)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=status_code, content=body)


@router.post("/sale", status_code=201)
def quick_sale(
    payload: QuickSaleCreate,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SALES_CREATE)),
):
    request_id = _request_id(request)
    with get_connection() as conn:
        service = QuickService(conn)

        def _do():
            try:
                result = service.quick_sale(
                    customer_id=payload.customer_id,
                    items=payload.items,
                    payments=[p.model_dump() for p in payload.payments],
                    discount_pct=payload.discount_pct,
                    discount_reason=payload.discount_reason,
                    auth=auth,
                )
            except NotFound as exc:
                raise _ApiError(404, str(exc))
            except InvalidState as exc:
                raise _ApiError(409, str(exc))
            except PermissionDenied as exc:
                raise _ApiError(403, str(exc))
            except ValueError as exc:
                raise _ApiError(422, str(exc))
            log_audit(
                conn, action="QUICK_SALE", user_id=auth.user_id,
                role_name=",".join(auth.roles), entity_type="sale",
                entity_id=result["id"],
                customer_id=result["customer_id"],
                amount=result["total"], ip_address=_client_ip(request),
            )
            return 201, _detail_to_response(result).model_dump(
                mode="json")

        try:
            if not request_id:
                status_code, body = _do()
            else:
                result = idempotent_call(
                    conn, request_id=request_id, action="quick.sale",
                    payload=payload.model_dump(mode="json"), fn=_do,
                )
                status_code, body = result.status_code, result.body
        except _ApiError as exc:
            raise HTTPException(status_code=exc.status,
                                detail=exc.detail)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=status_code, content=body)
