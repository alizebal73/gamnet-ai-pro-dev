import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.customer_service import CustomerService
from gamenet.server.services.idempotency import (
    IdempotencyConflict,
    idempotent_call,
)
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/customers", tags=["customers"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _create_customer(
    conn: sqlite3.Connection,
    payload: CustomerCreate,
    request: Request,
    auth: AuthContext,
) -> CustomerResponse:
    service = CustomerService(conn)
    customer = service.create_customer(payload)
    log_audit(
        conn, action="CUSTOMER_CREATE", user_id=auth.user_id,
        role_name=",".join(auth.roles), entity_type="customer",
        entity_id=customer.id, customer_id=customer.id,
        new_value=customer.name, ip_address=_client_ip(request),
    )
    return customer


@router.post("", response_model=CustomerResponse, status_code=201)
def create_customer(
    payload: CustomerCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_CREATE)),
):
    request_id = request.headers.get("x-request-id")
    if request_id is not None:
        request_id = request_id.strip()
        if not 1 <= len(request_id) <= 64:
            raise HTTPException(
                status_code=422, detail="Invalid X-Request-ID (1-64 chars)."
            )

    with get_connection() as conn:
        if not request_id:
            return _create_customer(conn, payload, request, auth)

        def _do():
            customer = _create_customer(conn, payload, request, auth)
            return 201, customer.model_dump(mode="json")

        try:
            result = idempotent_call(
                conn, request_id=request_id, action="customers.create",
                payload=payload.model_dump(mode="json"), fn=_do,
            )
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=result.status_code, content=result.body)


@router.get("/search", response_model=CustomerListResponse)
def search_customers(
    q: str = Query(min_length=1),
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> CustomerListResponse:
    with get_connection() as conn:
        service = CustomerService(conn)
        items = service.search(q)
        return CustomerListResponse(items=items, total=len(items))


@router.get("/by-number/{customer_number}", response_model=CustomerResponse)
def get_customer_by_number(
    customer_number: int,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> CustomerResponse:
    with get_connection() as conn:
        service = CustomerService(conn)
        customer = service.get_by_number(customer_number)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_VIEW)),
) -> CustomerResponse:
    with get_connection() as conn:
        service = CustomerService(conn)
        customer = service.get_by_id(customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer
