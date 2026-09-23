import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    PaymentCreate,
    PaymentResponse,
    SaleCancel,
    SaleCreate,
    SaleDetailResponse,
    SaleItemResponse,
    SaleListResponse,
    SaleResponse,
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
from gamenet.server.services.payment_service import PaymentService
from gamenet.server.services.sale_service import SaleService
from gamenet.shared.enums import Permission, SaleStatus

router = APIRouter(prefix="/sales", tags=["sales"])


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


def _payment_to_response(row: dict) -> PaymentResponse:
    return PaymentResponse(
        id=row["id"], sale_id=row["sale_id"], method=row["method"],
        amount=row["amount"], tendered=row["tendered"], status=row["status"],
        provider=row["provider"], provider_ref=row["provider_ref"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        paid_at=row["paid_at"],
    )


def _detail_to_response(detail: dict) -> SaleDetailResponse:
    return SaleDetailResponse(
        **{k: detail[k] for k in SaleResponse.model_fields},
        items=[
            SaleItemResponse(
                **{**item, "price_snapshot": json.loads(item["price_snapshot"])}
            )
            for item in detail["items"]
        ],
        payments=[_payment_to_response(p) for p in detail["payments"]],
    )


def _sale_to_response(row: dict) -> SaleResponse:
    return SaleResponse(**{k: row[k] for k in SaleResponse.model_fields})


@router.post("", response_model=SaleDetailResponse, status_code=201)
def create_sale(
    payload: SaleCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
):
    request_id = _request_id(request)
    with get_connection() as conn:
        service = SaleService(conn)

        def _do():
            try:
                detail = service.create_draft(
                    customer_id=payload.customer_id,
                    items=[i.model_dump() for i in payload.items],
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
                conn, action="SALE_CREATE", user_id=auth.user_id,
                role_name=",".join(auth.roles), entity_type="sale",
                entity_id=detail["id"], customer_id=detail["customer_id"],
                amount=detail["total"], ip_address=_client_ip(request),
            )
            return 201, _detail_to_response(detail).model_dump(mode="json")

        try:
            if not request_id:
                status_code, body = _do()
            else:
                result = idempotent_call(
                    conn, request_id=request_id, action="sales.create",
                    payload=payload.model_dump(mode="json"), fn=_do,
                )
                status_code, body = result.status_code, result.body
        except _ApiError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=status_code, content=body)


class _ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@router.get("", response_model=SaleListResponse)
def list_sales(
    customer_id: str | None = Query(default=None),
    status: SaleStatus | None = Query(default=None),
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> SaleListResponse:
    with get_connection() as conn:
        from gamenet.server.repositories.sale_repository import SaleRepository

        rows = SaleRepository(conn).list_sales(
            customer_id=customer_id, status=status.value if status else None
        )
        items = [_sale_to_response(r) for r in rows]
        return SaleListResponse(items=items, total=len(items))


@router.get("/{sale_id}", response_model=SaleDetailResponse)
def get_sale(
    sale_id: str,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> SaleDetailResponse:
    with get_connection() as conn:
        try:
            detail = SaleService(conn).detail(sale_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return _detail_to_response(detail)


@router.post("/{sale_id}/payments", response_model=PaymentResponse, status_code=201)
def add_payment(
    sale_id: str,
    payload: PaymentCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
):
    request_id = _request_id(request)
    with get_connection() as conn:
        service = PaymentService(conn)

        def _do():
            try:
                row = service.add_payment(
                    sale_id=sale_id, method=payload.method.value,
                    amount=payload.amount, provider_name=payload.provider,
                    provider_ref=payload.provider_ref, tendered=payload.tendered,
                    meta=payload.meta,
                )
            except NotFound as exc:
                raise _ApiError(404, str(exc))
            except InvalidState as exc:
                raise _ApiError(409, str(exc))
            except ValueError as exc:
                raise _ApiError(422, str(exc))
            log_audit(
                conn, action="PAYMENT_CREATE", user_id=auth.user_id,
                role_name=",".join(auth.roles), entity_type="payment",
                entity_id=row["id"], amount=row["amount"],
                new_value=row["status"], ip_address=_client_ip(request),
            )
            return 201, _payment_to_response(row).model_dump(mode="json")

        try:
            if not request_id:
                status_code, body = _do()
            else:
                result = idempotent_call(
                    conn, request_id=request_id, action="payments.create",
                    payload={"sale_id": sale_id, **payload.model_dump(mode="json")},
                    fn=_do,
                )
                status_code, body = result.status_code, result.body
        except _ApiError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=status_code, content=body)


@router.post("/{sale_id}/confirm", response_model=SaleDetailResponse)
def confirm_sale(
    sale_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
):
    request_id = _request_id(request)
    with get_connection() as conn:
        service = SaleService(conn)

        def _do():
            try:
                detail = service.confirm(sale_id, created_by=auth.user_id)
            except NotFound as exc:
                raise _ApiError(404, str(exc))
            except InvalidState as exc:
                raise _ApiError(409, str(exc))
            log_audit(
                conn, action="SALE_CONFIRM", user_id=auth.user_id,
                role_name=",".join(auth.roles), entity_type="sale",
                entity_id=sale_id, customer_id=detail["customer_id"],
                amount=detail["total"], ip_address=_client_ip(request),
            )
            return 200, _detail_to_response(detail).model_dump(mode="json")

        try:
            if not request_id:
                status_code, body = _do()
            else:
                result = idempotent_call(
                    conn, request_id=request_id, action="sales.confirm",
                    payload={"sale_id": sale_id}, fn=_do,
                )
                status_code, body = result.status_code, result.body
        except _ApiError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=status_code, content=body)


@router.post("/{sale_id}/cancel", response_model=SaleDetailResponse)
def cancel_sale(
    sale_id: str,
    payload: SaleCancel,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CANCEL)),
) -> SaleDetailResponse:
    with get_connection() as conn:
        try:
            detail = SaleService(conn).cancel(sale_id, reason=payload.reason)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        log_audit(
            conn, action="SALE_CANCEL", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="sale",
            entity_id=sale_id, reason=payload.reason,
            ip_address=_client_ip(request),
        )
        return _detail_to_response(detail)
