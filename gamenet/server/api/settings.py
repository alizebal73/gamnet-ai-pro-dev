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
KNOWN_SETTINGS = {
    "store_name", "base_currency_unit", "price_per_hour", "weekend_days",
    "operator_max_discount_pct", "vip_renewal_mode", "credit_priority",
    "agent_lease_sec", "agent_token_ttl_hours", "agent_command_ttl_sec",
}


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
    elif key == "operator_max_discount_pct":
        if not value.isdigit() or not 0 <= int(value) <= 100:
            raise ValueError("operator_max_discount_pct must be 0..100")
    elif key == "vip_renewal_mode":
        if value not in ("AFTER_EXPIRY", "NOW"):
            raise ValueError("vip_renewal_mode must be AFTER_EXPIRY or NOW")
    elif key == "credit_priority":
        if value not in ("EARLIEST_EXPIRY",):
            raise ValueError("credit_priority must be EARLIEST_EXPIRY")
    elif key == "agent_lease_sec":
        if not value.isdigit() or not 5 <= int(value) <= 600:
            raise ValueError("agent_lease_sec must be 5..600")
    elif key == "agent_token_ttl_hours":
        if not value.isdigit() or not 1 <= int(value) <= 720:
            raise ValueError("agent_token_ttl_hours must be 1..720")
    elif key == "agent_command_ttl_sec":
        if not value.isdigit() or not 10 <= int(value) <= 86400:
            raise ValueError("agent_command_ttl_sec must be 10..86400")


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
