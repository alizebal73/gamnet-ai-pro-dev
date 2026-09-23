from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from gamenet.server.api.deps import require_permission
from gamenet.server.db import get_connection
from gamenet.server.models.schemas import (
    PricingRuleCreate,
    PricingRuleListResponse,
    PricingRuleResponse,
    PricingRuleUpdate,
    QuoteRequest,
    QuoteResponse,
)
from gamenet.server.services.audit_service import log_audit
from gamenet.server.services.auth_service import AuthContext
from gamenet.server.services.idempotency import (
    IdempotencyConflict,
    idempotent_call,
)
from gamenet.server.services.pricing_service import PricingService
from gamenet.shared.enums import Permission

router = APIRouter(prefix="/pricing", tags=["pricing"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _to_response(row: dict) -> PricingRuleResponse:
    return PricingRuleResponse(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        duration_sec=row["duration_sec"],
        price=row["price"],
        factor_pct=row["factor_pct"],
        pc_class=row["pc_class"],
        scope=row["scope"],
        window_start_min=row["window_start_min"],
        window_end_min=row["window_end_min"],
        priority=row["priority"],
        active=bool(row["active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/quote", response_model=QuoteResponse)
def quote_price(
    payload: QuoteRequest,
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> QuoteResponse:
    with get_connection() as conn:
        try:
            result = PricingService(conn).quote(
                duration_sec=payload.duration_sec,
                pc_class=payload.pc_class,
                at=payload.at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return QuoteResponse(
            total=result.total,
            currency_unit=result.currency_unit,
            base_total=result.base_total,
            base_rule_id=result.base_rule_id,
            multiplier_pct=result.multiplier_pct,
            multiplier_rule_id=result.multiplier_rule_id,
            snapshot=result.snapshot,
        )


@router.get("/rules", response_model=PricingRuleListResponse)
def list_rules(
    active_only: bool = Query(default=True),
    auth: AuthContext = Depends(require_permission(Permission.SALES_CREATE)),
) -> PricingRuleListResponse:
    with get_connection() as conn:
        rows = PricingService(conn).list_rules(active_only=active_only)
        items = [_to_response(r) for r in rows]
        return PricingRuleListResponse(items=items, total=len(items))


@router.post("/rules", response_model=PricingRuleResponse, status_code=201)
def create_rule(
    payload: PricingRuleCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
):
    request_id = request.headers.get("x-request-id")
    if request_id is not None:
        request_id = request_id.strip()
        if not 1 <= len(request_id) <= 64:
            raise HTTPException(
                status_code=422, detail="Invalid X-Request-ID (1-64 chars)."
            )

    with get_connection() as conn:
        service = PricingService(conn)

        def _do():
            try:
                row = service.create_rule(**payload.model_dump())
            except ValueError as exc:
                raise _RuleError(str(exc))
            log_audit(
                conn, action="PRICING_RULE_CREATE", user_id=auth.user_id,
                role_name=",".join(auth.roles), entity_type="pricing_rule",
                entity_id=row["id"], new_value=payload.model_dump_json(),
                ip_address=_client_ip(request),
            )
            return 201, _to_response(row).model_dump(mode="json")

        try:
            if not request_id:
                status_code, body = _do()
                return JSONResponse(status_code=status_code, content=body)
            result = idempotent_call(
                conn, request_id=request_id, action="pricing.rule.create",
                payload=payload.model_dump(mode="json"), fn=_do,
            )
        except _RuleError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return JSONResponse(status_code=result.status_code, content=result.body)


class _RuleError(Exception):
    pass


@router.patch("/rules/{rule_id}", response_model=PricingRuleResponse)
def update_rule(
    rule_id: str,
    payload: PricingRuleUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission(Permission.SETTINGS_EDIT)),
) -> PricingRuleResponse:
    with get_connection() as conn:
        service = PricingService(conn)
        before = service.get_rule(rule_id)
        if before is None:
            raise HTTPException(status_code=404, detail="Pricing rule not found")
        try:
            row = service.update_rule(
                rule_id, payload.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        log_audit(
            conn, action="PRICING_RULE_UPDATE", user_id=auth.user_id,
            role_name=",".join(auth.roles), entity_type="pricing_rule",
            entity_id=rule_id,
            old_value=f"price={before['price']} factor={before['factor_pct']} active={before['active']}",
            new_value=f"price={row['price']} factor={row['factor_pct']} active={row['active']}",
            ip_address=_client_ip(request),
        )
        return _to_response(row)
