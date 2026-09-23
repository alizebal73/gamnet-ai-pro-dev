"""Snack/bar inventory endpoints (P3-3)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    StockAdjustRequest,
    StockLedgerResponse,
    StockReceiveRequest,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.inventory_service import InventoryService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/items", response_model=InventoryItemResponse, status_code=201)
def create_item(
    payload: InventoryItemCreate,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_ADJUST)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            item = InventoryService(conn).create_item(
                sku=payload.sku, name=payload.name,
                unit_price=payload.unit_price,
                low_stock_at=payload.low_stock_at,
            )
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="INVENTORY_CREATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="inventory_item",
            entity_id=item["id"], amount=payload.unit_price,
            reason=f"{payload.sku}: {payload.name}",
            ip_address=_ip(request),
        )
        return InventoryItemResponse(**item)


@router.get("/items", response_model=list[InventoryItemResponse])
def list_items(
    status: str | None = Query(default=None),
    low_only: bool = Query(default=False),
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_SELL)),
) -> list[InventoryItemResponse]:
    with get_connection() as conn:
        return [InventoryItemResponse(**i) for i in
                InventoryService(conn).list_items(
                    status=status, low_only=low_only)]


@router.get("/items/{item_id}", response_model=InventoryItemResponse)
def get_item(
    item_id: str,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_SELL)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            return InventoryItemResponse(
                **InventoryService(conn).get(item_id))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/items/{item_id}", response_model=InventoryItemResponse)
def update_item(
    item_id: str,
    payload: InventoryItemUpdate,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_ADJUST)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            item = InventoryService(conn).update_item(
                item_id, name=payload.name,
                unit_price=payload.unit_price,
                low_stock_at=payload.low_stock_at,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="INVENTORY_UPDATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="inventory_item",
            entity_id=item_id, ip_address=_ip(request),
        )
        return InventoryItemResponse(**item)


@router.post("/items/{item_id}/archive",
             response_model=InventoryItemResponse)
def archive_item(
    item_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_ADJUST)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            item = InventoryService(conn).set_archived(item_id, True)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        log_audit(
            conn, action="INVENTORY_ARCHIVE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="inventory_item",
            entity_id=item_id, ip_address=_ip(request),
        )
        return InventoryItemResponse(**item)


@router.post("/items/{item_id}/unarchive",
             response_model=InventoryItemResponse)
def unarchive_item(
    item_id: str,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_ADJUST)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            item = InventoryService(conn).set_archived(item_id, False)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return InventoryItemResponse(**item)


@router.post("/items/{item_id}/receive",
             response_model=InventoryItemResponse)
def receive_stock(
    item_id: str,
    payload: StockReceiveRequest,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_ADJUST)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            item = InventoryService(conn).receive(
                item_id, qty=payload.qty, created_by=auth.user_id,
                reason=payload.reason,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="INVENTORY_RECEIVE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="inventory_item",
            entity_id=item_id, amount=payload.qty,
            reason=payload.reason, ip_address=_ip(request),
        )
        return InventoryItemResponse(**item)


@router.post("/items/{item_id}/adjust",
             response_model=InventoryItemResponse)
def adjust_stock(
    item_id: str,
    payload: StockAdjustRequest,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_ADJUST)),
) -> InventoryItemResponse:
    with get_connection() as conn:
        try:
            item = InventoryService(conn).adjust(
                item_id, delta=payload.delta, reason=payload.reason,
                created_by=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log_audit(
            conn, action="INVENTORY_ADJUST", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="inventory_item",
            entity_id=item_id, amount=payload.delta,
            reason=payload.reason, ip_address=_ip(request),
        )
        return InventoryItemResponse(**item)


@router.get("/items/{item_id}/ledger",
            response_model=list[StockLedgerResponse])
def item_ledger(
    item_id: str,
    auth: AuthContext = Depends(
        require_permission(Permission.INVENTORY_SELL)),
) -> list[StockLedgerResponse]:
    with get_connection() as conn:
        try:
            entries = InventoryService(conn).ledger(item_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return [StockLedgerResponse(**e) for e in entries]
