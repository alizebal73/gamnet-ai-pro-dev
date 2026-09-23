from pydantic import BaseModel, Field

from datetime import datetime

from gamenet.shared.enums import (
    CustomerStatus,
    EntitlementKind,
    EntitlementStatus,
    PaymentMethod,
    PaymentStatus,
    PCStatus,
    PricingKind,
    PricingScope,
    SaleItemKind,
    SaleStatus,
    SessionStatus,
    UserStatus,
)


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    migrations_applied: list[int]


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mobile: str | None = Field(default=None, max_length=20)
    gaming_name: str | None = Field(default=None, max_length=100)
    pin: str = Field(min_length=4, max_length=32)


class CustomerResponse(BaseModel):
    id: str
    customer_number: int
    name: str
    mobile: str | None
    gaming_name: str | None
    status: CustomerStatus
    created_at: str
    updated_at: str


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthUserResponse(BaseModel):
    id: str
    username: str
    display_name: str | None
    status: UserStatus
    roles: list[str]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: AuthUserResponse


class MeResponse(BaseModel):
    user: AuthUserResponse
    permissions: list[str]


class PricingRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: PricingKind
    duration_sec: int | None = Field(default=None, gt=0)
    price: int | None = Field(default=None, ge=0)
    factor_pct: int | None = Field(default=None, ge=1, le=1000)
    pc_class: str | None = Field(default=None, max_length=50)
    scope: PricingScope = PricingScope.ANY
    window_start_min: int | None = Field(default=None, ge=0, le=1439)
    window_end_min: int | None = Field(default=None, ge=0, le=1439)
    priority: int = 100
    active: bool = True


class PricingRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: PricingKind | None = None
    duration_sec: int | None = Field(default=None, gt=0)
    price: int | None = Field(default=None, ge=0)
    factor_pct: int | None = Field(default=None, ge=1, le=1000)
    pc_class: str | None = Field(default=None, max_length=50)
    scope: PricingScope | None = None
    window_start_min: int | None = Field(default=None, ge=0, le=1439)
    window_end_min: int | None = Field(default=None, ge=0, le=1439)
    priority: int | None = None
    active: bool | None = None


class PricingRuleResponse(BaseModel):
    id: str
    name: str
    kind: PricingKind
    duration_sec: int | None
    price: int | None
    factor_pct: int | None
    pc_class: str | None
    scope: PricingScope
    window_start_min: int | None
    window_end_min: int | None
    priority: int
    active: bool
    created_at: str
    updated_at: str


class PricingRuleListResponse(BaseModel):
    items: list[PricingRuleResponse]
    total: int


class QuoteRequest(BaseModel):
    duration_sec: int = Field(gt=0, le=2592000)
    pc_class: str | None = Field(default=None, max_length=50)
    at: datetime | None = None


class QuoteResponse(BaseModel):
    total: int
    currency_unit: str
    base_total: int
    base_rule_id: str | None
    multiplier_pct: int | None
    multiplier_rule_id: str | None
    snapshot: dict


class SettingResponse(BaseModel):
    key: str
    value: str
    updated_at: str


class SettingListResponse(BaseModel):
    items: list[SettingResponse]


class SettingUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=500)


class SaleItemCreate(BaseModel):
    kind: SaleItemKind
    label: str | None = Field(default=None, max_length=200)
    qty: int = Field(default=1, ge=1, le=100)
    duration_sec: int | None = Field(default=None, gt=0)
    pc_class: str | None = Field(default=None, max_length=50)
    unit_price: int | None = Field(default=None, ge=0)
    ref_id: str | None = Field(default=None, max_length=50)


class SaleCreate(BaseModel):
    customer_id: str = Field(min_length=1)
    items: list[SaleItemCreate] = Field(min_length=1, max_length=50)
    discount_pct: int = Field(default=0, ge=0, le=100)
    discount_reason: str | None = Field(default=None, max_length=300)


class SaleItemResponse(BaseModel):
    id: str
    kind: SaleItemKind
    label: str
    qty: int
    unit_price: int
    total_price: int
    duration_sec: int | None
    pc_class: str | None
    ref_id: str | None
    price_snapshot: dict


class PaymentResponse(BaseModel):
    id: str
    sale_id: str
    method: PaymentMethod
    amount: int
    tendered: int | None
    status: PaymentStatus
    provider: str
    provider_ref: str | None
    created_at: str
    updated_at: str
    paid_at: str | None


class SaleResponse(BaseModel):
    id: str
    customer_id: str
    operator_user_id: str
    status: SaleStatus
    subtotal: int
    discount_pct: int
    discount_amount: int
    discount_reason: str | None
    total: int
    cancel_reason: str | None
    created_at: str
    updated_at: str
    confirmed_at: str | None
    cancelled_at: str | None
    shift_id: str | None = None


class RefundCreate(BaseModel):
    amount: int = Field(gt=0)
    method: str = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=300)


class RefundResponse(BaseModel):
    id: str
    sale_id: str
    amount: int
    method: str
    reason: str
    created_by: str
    shift_id: str | None
    created_at: str


class RefundResultResponse(BaseModel):
    refund: RefundResponse
    revoked_sec: int
    clawed_balance: int
    vips_cancelled: list[str]
    refunded_total: int


class SaleDetailResponse(SaleResponse):
    items: list[SaleItemResponse]
    payments: list[PaymentResponse]
    refunds: list[RefundResponse] = []
    refunded_total: int = 0


class SaleListResponse(BaseModel):
    items: list[SaleResponse]
    total: int


class PaymentCreate(BaseModel):
    method: PaymentMethod
    amount: int = Field(gt=0)
    provider: str | None = Field(default=None, max_length=30)
    provider_ref: str | None = Field(default=None, max_length=100)
    tendered: int | None = Field(default=None, ge=0)
    meta: dict | None = None


class SaleCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int


class PackageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    duration_sec: int = Field(gt=0)
    price: int = Field(gt=0)
    bonus_sec: int = Field(default=0, ge=0)
    validity_days: int | None = Field(default=None, gt=0)


class PackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    duration_sec: int | None = Field(default=None, gt=0)
    price: int | None = Field(default=None, gt=0)
    bonus_sec: int | None = Field(default=None, ge=0)
    validity_days: int | None = Field(default=None, gt=0)
    active: bool | None = None


class PackageResponse(BaseModel):
    id: str
    name: str
    duration_sec: int
    price: int
    bonus_sec: int
    validity_days: int | None
    active: bool
    created_at: str
    updated_at: str


class PackageListResponse(BaseModel):
    items: list[PackageResponse]
    total: int


class VipPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    duration_days: int = Field(gt=0)
    price: int = Field(gt=0)
    discount_pct: int = Field(default=0, ge=0, le=100)


class VipPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    duration_days: int | None = Field(default=None, gt=0)
    price: int | None = Field(default=None, gt=0)
    discount_pct: int | None = Field(default=None, ge=0, le=100)
    active: bool | None = None


class VipPlanResponse(BaseModel):
    id: str
    name: str
    duration_days: int
    price: int
    discount_pct: int
    active: bool
    created_at: str
    updated_at: str


class VipPlanListResponse(BaseModel):
    items: list[VipPlanResponse]
    total: int


class EntitlementResponse(BaseModel):
    id: str
    customer_id: str
    kind: EntitlementKind
    status: EntitlementStatus
    effective_status: EntitlementStatus | None = None
    granted_sec: int | None
    consumed_sec: int
    remaining_sec: int | None = None
    starts_at: str
    expires_at: str | None
    discount_pct: int
    sale_id: str | None
    sale_item_id: str | None
    ref_id: str | None
    created_at: str
    updated_at: str


class CreditSummaryResponse(BaseModel):
    customer_id: str
    total_remaining_sec: int
    active_vip: EntitlementResponse | None
    entitlements: list[EntitlementResponse]


class BalanceAdjust(BaseModel):
    amount: int
    reason: str = Field(min_length=1, max_length=300)


class BalanceLedgerEntry(BaseModel):
    id: str
    customer_id: str
    amount: int
    balance_after: int
    kind: str
    ref_type: str | None
    ref_id: str | None
    reason: str | None
    created_at: str


class BalanceResponse(BaseModel):
    customer_id: str
    balance: int
    currency_unit: str


class BalanceLedgerResponse(BaseModel):
    items: list[BalanceLedgerEntry]
    total: int


class SessionCreate(BaseModel):
    customer_id: str = Field(min_length=1)
    pc_id: str | None = None


class SessionAuthorize(BaseModel):
    pc_id: str | None = None


class SessionPause(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class SessionEnd(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class SessionTransfer(BaseModel):
    new_pc_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=300)


class SessionEventResponse(BaseModel):
    id: str
    kind: str
    from_status: str | None
    to_status: str | None
    pc_id: str | None
    actor_user_id: str | None
    reason: str | None
    created_at: str


class SessionConsumptionResponse(BaseModel):
    id: str
    entitlement_id: str | None
    seconds: int
    period_start: str
    period_end: str
    kind: str
    created_at: str


class SessionResponse(BaseModel):
    id: str
    customer_id: str
    pc_id: str | None
    status: SessionStatus
    created_by: str | None
    started_at: str | None
    last_accounted_at: str | None
    ended_at: str | None
    ended_reason: str | None
    total_consumed_sec: int
    created_at: str
    updated_at: str


class SessionDetailResponse(SessionResponse):
    events: list[SessionEventResponse]
    consumptions: list[SessionConsumptionResponse]
    customer_remaining_sec: int


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int


class PcCreate(BaseModel):
    device_code: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)


class PcUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    status: str | None = None
    reason: str | None = Field(default=None, max_length=300)


class PcResponse(BaseModel):
    id: str
    device_code: str
    display_name: str
    status: PCStatus
    agent_version: str | None
    last_seen_at: str | None
    created_at: str
    updated_at: str


class PcListResponse(BaseModel):
    items: list[PcResponse]
    total: int


class PcSecretResponse(BaseModel):
    pc_id: str
    secret: str


class SafeModeRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=300)


class SafeModeResponse(BaseModel):
    safe_mode: bool
    reason: str


class AuditResponse(BaseModel):
    id: str
    timestamp: str
    user_id: str | None
    role_name: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    old_value: str | None
    new_value: str | None
    amount: int | None
    pc_id: str | None
    customer_id: str | None
    reason: str | None
    request_id: str | None
    ip_address: str | None


class AuditListResponse(BaseModel):
    items: list[AuditResponse]
    total: int


class AuditVerifyResponse(BaseModel):
    checked: int
    skipped: int
    ok: bool
    broken_id: str | None
    reason: str | None


class ReconcileResponse(BaseModel):
    id: str
    started_at: str
    finished_at: str
    status: str
    issues: list[dict]
    triggered_by: str | None


class AgentAuthRequest(BaseModel):
    device_code: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    agent_version: str | None = Field(default=None, max_length=32)


class AgentAuthResponse(BaseModel):
    pc_id: str
    token: str
    expires_at: str


class HeartbeatRequest(BaseModel):
    session_id: str | None = None
    agent_version: str | None = Field(default=None, max_length=32)
    cpu_pct: float | None = None
    mem_pct: float | None = None
    disk_free_mb: int | None = None


class AgentCommandPayload(BaseModel):
    id: str
    type: str
    payload: dict = {}


class HeartbeatResponse(BaseModel):
    server_time: str
    lease_sec: int
    lease_until: str
    commands: list[AgentCommandPayload] = []
    session: dict | None = None


class CommandAckRequest(BaseModel):
    ok: bool = True
    result: dict | None = None


class CommandResponse(BaseModel):
    id: str
    pc_id: str
    type: str
    status: str
    created_at: str
    sent_at: str | None
    acked_at: str | None
    expires_at: str
    result: dict | None = None

    @classmethod
    def from_row(cls, row: dict) -> "CommandResponse":
        import json as _json

        raw = row.get("result_json")
        return cls(
            id=row["id"], pc_id=row["pc_id"], type=row["type"],
            status=row["status"], created_at=row["created_at"],
            sent_at=row.get("sent_at"), acked_at=row.get("acked_at"),
            expires_at=row["expires_at"],
            result=_json.loads(raw) if raw else None,
        )


class QueueCommandRequest(BaseModel):
    type: str = Field(min_length=1, max_length=32)
    payload: dict = {}


class ShiftOpenRequest(BaseModel):
    opening_float: int = Field(default=0, ge=0)


class ShiftCloseRequest(BaseModel):
    counted_cash: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)


class CashMovementRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=8)
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=300)


class CashMovementResponse(BaseModel):
    id: str
    shift_id: str
    kind: str
    amount: int
    reason: str
    created_by: str
    created_at: str


class ShiftResponse(BaseModel):
    id: str
    status: str
    opened_by: str
    opened_at: str
    closed_by: str | None
    closed_at: str | None
    opening_float: int
    expected_cash: int | None
    counted_cash: int | None
    variance: int | None
    note: str | None
    cash_paid: int = 0
    moved_in: int = 0
    moved_out: int = 0
    expected_live: int | None = None


class PresenceResponse(BaseModel):
    pc_id: str
    online: bool
    last_seen: str
    lease_until: str
    session_id: str | None = None
    agent_version: str | None = None
    socket_connected: bool = False
    ip: str | None = None
