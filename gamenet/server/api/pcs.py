from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import get_current_user, require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    PcCreate,
    PcHealthResponse,
    PcListResponse,
    PcResponse,
    PcSecretResponse,
    PcUpdate,
)
from gamenet.server.repositories.pc_repository import PcRepository
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.pc_service import PcService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/pcs", tags=["pcs"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _to_response(row: dict) -> PcResponse:
    return PcResponse(
        id=row["id"], device_code=row["device_code"],
        display_name=row["display_name"], status=row["status"],
        agent_version=row["agent_version"], last_seen_at=row["last_seen_at"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


@router.get("", response_model=PcListResponse)
def list_pcs(
    auth: AuthContext = Depends(get_current_user),
) -> PcListResponse:
    with get_connection() as conn:
        rows = PcRepository(conn).list_pcs()
        items = [_to_response(r) for r in rows]
        return PcListResponse(items=items, total=len(items))


@router.get("/{pc_id}", response_model=PcResponse)
def get_pc(
    pc_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> PcResponse:
    with get_connection() as conn:
        row = PcRepository(conn).get(pc_id)
        if row is None:
            raise HTTPException(status_code=404, detail="PC not found")
        return _to_response(row)


@router.post("", response_model=PcResponse, status_code=201)
def register_pc(
    payload: PcCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> PcResponse:
    with get_connection() as conn:
        try:
            row = PcService(conn).register(
                device_code=payload.device_code,
                display_name=payload.display_name,
            )
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        log_audit(
            conn, action="PC_REGISTER", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="pc",
            entity_id=row["id"], pc_id=row["id"],
            new_value=payload.device_code, ip_address=_client_ip(request),
        )
        return _to_response(row)


@router.patch("/{pc_id}", response_model=PcResponse)
def update_pc(
    pc_id: str,
    payload: PcUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> PcResponse:
    with get_connection() as conn:
        service = PcService(conn)
        try:
            row = None
            if payload.display_name is not None:
                row = service.rename(pc_id, payload.display_name)
            if payload.status is not None:
                row = service.set_status(
                    pc_id, payload.status, reason=payload.reason,
                    actor_user_id=auth.user_id,
                )
            if row is None:
                row = PcRepository(conn).get(pc_id)
                if row is None:
                    raise HTTPException(status_code=404, detail="PC not found")
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        log_audit(
            conn, action="PC_UPDATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="pc",
            entity_id=pc_id, pc_id=pc_id,
            new_value=payload.model_dump_json(exclude_unset=True),
            ip_address=_client_ip(request),
        )
        return _to_response(row)


@router.post("/{pc_id}/rotate-secret", response_model=PcSecretResponse)
def rotate_secret(
    pc_id: str,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> PcSecretResponse:
    with get_connection() as conn:
        try:
            result = PcService(conn).rotate_secret(pc_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        log_audit(
            conn, action="PC_SECRET_ROTATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="pc",
            entity_id=pc_id, pc_id=pc_id, ip_address=_client_ip(request),
        )
        return PcSecretResponse(**result)


@router.get("/{pc_id}/health", response_model=PcHealthResponse)
def pc_health(
    pc_id: str,
    limit: int = 50,
    auth: AuthContext = Depends(
        require_permission(Permission.REPORTS_VIEW)),
) -> PcHealthResponse:
    limit = max(1, min(limit, 500))
    with get_connection() as conn:
        pc = PcRepository(conn).get(pc_id)
        if pc is None:
            raise HTTPException(status_code=404, detail="PC not found")
        rows = conn.execute(
            """SELECT cpu_pct, mem_pct, disk_free_mb, temp_c, recorded_at
               FROM pc_health WHERE pc_id = ?
               ORDER BY recorded_at DESC, id DESC LIMIT ?""",
            (pc_id, limit),
        ).fetchall()
        samples = [dict(r) for r in rows]
        return PcHealthResponse(
            pc_id=pc_id, status=pc["status"],
            last_seen_at=pc["last_seen_at"],
            latest=samples[0] if samples else None,
            samples=samples,
        )
