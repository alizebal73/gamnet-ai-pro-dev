from fastapi import APIRouter, Depends, HTTPException, Request

from gamenet.server.api.deps import get_current_user, require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from gamenet.server.repositories.settings_repository import SettingsRepository
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/settings", tags=["settings"])

# Whitelist of editable settings with validators (Master Spec 320 subset).
KNOWN_SETTINGS = {"store_name", "base_currency_unit", "price_per_hour", "weekend_days"}


def _validate_setting(key: str, value: str) -> None:
    if key not in KNOWN_SETTINGS:
        raise ValueError(f"Unknown setting: {key}")
    if key == "price_per_hour":
        if not value.isdigit() or int(value) < 0:
            raise ValueError("price_per_hour must be a non-negative integer")
    elif key == "weekend_days":
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not parts or any(not p.isdigit() or int(p) > 6 for p in parts):
            raise ValueError("weekend_days must be comma-separated day numbers 0-6")
    elif key == "base_currency_unit":
        if not value.strip() or len(value) > 10:
            raise ValueError("base_currency_unit must be 1-10 characters")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=SettingListResponse)
def list_settings(
    auth: AuthContext = Depends(get_current_user),
) -> SettingListResponse:
    with get_connection() as conn:
        rows = SettingsRepository(conn).list_all()
        return SettingListResponse(
            items=[SettingResponse(**r) for r in rows]
        )


@router.put("/{key}", response_model=SettingResponse)
def update_setting(
    key: str,
    payload: SettingUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> SettingResponse:
    try:
        _validate_setting(key, payload.value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with get_connection() as conn:
        repo = SettingsRepository(conn)
        old = repo.get(key)
        row = repo.set(key, payload.value.strip())
        log_audit(
            conn, action="SETTING_CHANGE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="setting",
            entity_id=key, old_value=old, new_value=row["value"],
            ip_address=_client_ip(request),
        )
        return SettingResponse(**row)
