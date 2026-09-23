import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    PackageCreate,
    PackageListResponse,
    PackageResponse,
    PackageUpdate,
    VipPlanCreate,
    VipPlanListResponse,
    VipPlanResponse,
    VipPlanUpdate,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.catalog_service import CatalogService
from gamenet.shared.enums import Permission

router = APIRouter(tags=["catalog"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _pkg(row: dict) -> PackageResponse:
    return PackageResponse(
        id=row["id"], name=row["name"], duration_sec=row["duration_sec"],
        price=row["price"], bonus_sec=row["bonus_sec"],
        validity_days=row["validity_days"], active=bool(row["active"]),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _plan(row: dict) -> VipPlanResponse:
    return VipPlanResponse(
        id=row["id"], name=row["name"], duration_days=row["duration_days"],
        price=row["price"], discount_pct=row["discount_pct"],
        active=bool(row["active"]), created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---- packages ----

@router.get("/packages", response_model=PackageListResponse)
def list_packages(
    active_only: bool = Query(default=True),
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> PackageListResponse:
    with get_connection() as conn:
        rows = CatalogService(conn).list_packages(active_only=active_only)
        items = [_pkg(r) for r in rows]
        return PackageListResponse(items=items, total=len(items))


@router.post("/packages", response_model=PackageResponse, status_code=201)
def create_package(
    payload: PackageCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> PackageResponse:
    with get_connection() as conn:
        try:
            row = CatalogService(conn).create_package(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="Package name already exists"
            )
        log_audit(
            conn, action="PACKAGE_CREATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="package",
            entity_id=row["id"], new_value=row["name"],
            ip_address=_client_ip(request),
        )
        return _pkg(row)


@router.patch("/packages/{pkg_id}", response_model=PackageResponse)
def update_package(
    pkg_id: str,
    payload: PackageUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> PackageResponse:
    with get_connection() as conn:
        service = CatalogService(conn)
        if service.get_package(pkg_id) is None:
            raise HTTPException(status_code=404, detail="Package not found")
        try:
            row = service.update_package(
                pkg_id, payload.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="Package name already exists"
            )
        log_audit(
            conn, action="PACKAGE_UPDATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="package",
            entity_id=pkg_id, ip_address=_client_ip(request),
        )
        return _pkg(row)


# ---- VIP plans ----

@router.get("/vip-plans", response_model=VipPlanListResponse)
def list_vip_plans(
    active_only: bool = Query(default=True),
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> VipPlanListResponse:
    with get_connection() as conn:
        rows = CatalogService(conn).list_vip_plans(active_only=active_only)
        items = [_plan(r) for r in rows]
        return VipPlanListResponse(items=items, total=len(items))


@router.post("/vip-plans", response_model=VipPlanResponse, status_code=201)
def create_vip_plan(
    payload: VipPlanCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> VipPlanResponse:
    with get_connection() as conn:
        try:
            row = CatalogService(conn).create_vip_plan(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="VIP plan name already exists"
            )
        log_audit(
            conn, action="VIP_PLAN_CREATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="vip_plan",
            entity_id=row["id"], new_value=row["name"],
            ip_address=_client_ip(request),
        )
        return _plan(row)


@router.patch("/vip-plans/{plan_id}", response_model=VipPlanResponse)
def update_vip_plan(
    plan_id: str,
    payload: VipPlanUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> VipPlanResponse:
    with get_connection() as conn:
        service = CatalogService(conn)
        if service.get_vip_plan(plan_id) is None:
            raise HTTPException(status_code=404, detail="VIP plan not found")
        try:
            row = service.update_vip_plan(
                plan_id, payload.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="VIP plan name already exists"
            )
        log_audit(
            conn, action="VIP_PLAN_UPDATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="vip_plan",
            entity_id=plan_id, ip_address=_client_ip(request),
        )
        return _plan(row)
