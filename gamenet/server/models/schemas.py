from pydantic import BaseModel, Field

from gamenet.shared.enums import CustomerStatus, UserStatus


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
