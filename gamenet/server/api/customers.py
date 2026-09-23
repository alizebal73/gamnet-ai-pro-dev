from fastapi import APIRouter, Depends, HTTPException, Query, Request

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
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/customers", tags=["customers"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=CustomerResponse, status_code=201)
def create_customer(
    payload: CustomerCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.CUSTOMER_CREATE)),
) -> CustomerResponse:
    with get_connection() as conn:
        service = CustomerService(conn)
        customer = service.create_customer(payload)
        log_audit(
            conn, action="CUSTOMER_CREATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="customer",
            entity_id=customer.id, customer_id=customer.id,
            new_value=customer.name, ip_address=_client_ip(request),
        )
        return customer


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
