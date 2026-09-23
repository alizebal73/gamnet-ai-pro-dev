from pydantic import BaseModel, Field

from datetime import datetime

from gamenet.shared.enums import (
    CustomerStatus,
    PricingKind,
    PricingScope,
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
