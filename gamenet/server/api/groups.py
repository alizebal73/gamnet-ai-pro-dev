"""Group sessions: link sessions that end together."""

from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    GroupCreate,
    GroupEndAll,
    GroupEndResult,
    GroupMemberAdd,
    GroupResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.errors import InvalidState, NotFound
from gamenet.server.services.group_service import GroupService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/session-groups", tags=["groups"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(conn, action, auth, group_id, request, reason=None):
    log_audit(
        conn, action=action, user_id=auth.user_id,
        role_name=",".join(auth.roles), entity_type="session_group",
        entity_id=group_id, reason=reason, ip_address=_ip(request),
    )


@router.post("", response_model=GroupResponse, status_code=201)
def create_group(
    payload: GroupCreate,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> GroupResponse:
    with get_connection() as conn:
        try:
            group = GroupService(conn).create(
                name=payload.name,
                shared_ends_at=payload.shared_ends_at,
                created_by=auth.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _audit(conn, "GROUP_CREATE", auth, group["id"], request)
        return GroupResponse(**group)


@router.get("", response_model=list[GroupResponse])
def list_groups(
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> list[GroupResponse]:
    with get_connection() as conn:
        return [GroupResponse(**g)
                for g in GroupService(conn).list_open()]


@router.get("/{group_id}", response_model=GroupResponse)
def get_group(
    group_id: str,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> GroupResponse:
    with get_connection() as conn:
        try:
            return GroupResponse(**GroupService(conn).get(group_id))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{group_id}/members", response_model=GroupResponse)
def add_member(
    group_id: str,
    payload: GroupMemberAdd,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> GroupResponse:
    with get_connection() as conn:
        try:
            group = GroupService(conn).add_member(
                group_id, payload.session_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "GROUP_MEMBER_ADD", auth, group_id, request,
               reason=payload.session_id)
        return GroupResponse(**group)


@router.delete("/{group_id}/members/{session_id}",
               response_model=GroupResponse)
def remove_member(
    group_id: str,
    session_id: str,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> GroupResponse:
    with get_connection() as conn:
        try:
            group = GroupService(conn).remove_member(group_id,
                                                     session_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return GroupResponse(**group)


@router.post("/{group_id}/end-all", response_model=GroupEndResult)
def end_all(
    group_id: str,
    payload: GroupEndAll,
    request: Request,
    auth: AuthContext = Depends(
        require_permission(Permission.SESSION_OPERATE)),
) -> GroupEndResult:
    with get_connection() as conn:
        try:
            result = GroupService(conn).end_all(
                group_id, reason=payload.reason,
                actor_user_id=auth.user_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except InvalidState as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        _audit(conn, "GROUP_END_ALL", auth, group_id, request,
               reason=payload.reason)
        return GroupEndResult(
            group=GroupResponse(**result["group"]),
            ended=result["ended"], skipped=result["skipped"],
        )
