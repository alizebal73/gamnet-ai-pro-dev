from enum import StrEnum


class CustomerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class PCStatus(StrEnum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    READY = "READY"
    BUSY = "BUSY"
    PAUSED = "PAUSED"
    MAINTENANCE = "MAINTENANCE"
    ERROR = "ERROR"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"


class RoleName(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    OPERATOR = "operator"
    TECHNICIAN = "technician"
    VIEWER = "viewer"


class Permission(StrEnum):
    SALES_CREATE = "sales.create"
    SALES_CANCEL = "sales.cancel"
    SALES_REFUND = "sales.refund"
    CUSTOMER_CREATE = "customer.create"
    CUSTOMER_VIEW = "customer.view"
    CUSTOMER_EDIT = "customer.edit"
    CUSTOMER_EDIT_BALANCE = "customer.edit_balance"
    VIP_SELL = "vip.sell"
    VIP_CANCEL = "vip.cancel"
    DISCOUNT_APPLY = "discount.apply"
    INVENTORY_SELL = "inventory.sell"
    INVENTORY_ADJUST = "inventory.adjust"
    REPORTS_VIEW = "reports.view"
    REPORTS_FINANCIAL = "reports.financial"
    EMPLOYEE_MANAGE = "employee.manage"
    SETTINGS_EDIT = "settings.edit"
    BACKUP_MANAGE = "backup.manage"
    REMOTE_EXECUTE = "remote.execute"
    SESSION_OPERATE = "session.operate"
    SHIFT_MANAGE = "shift.manage"


class ShiftStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CashMovementKind(StrEnum):
    IN = "IN"
    OUT = "OUT"


class PricingKind(StrEnum):
    PER_HOUR = "PER_HOUR"
    FLAT = "FLAT"
    MULTIPLIER = "MULTIPLIER"


class PricingScope(StrEnum):
    ANY = "ANY"
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"


class SaleStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SaleItemKind(StrEnum):
    TIME = "TIME"
    VIP = "VIP"
    PACKAGE = "PACKAGE"
    RECHARGE = "RECHARGE"
    FOOD = "FOOD"
    ACCESSORY = "ACCESSORY"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    CARD = "CARD"
    BALANCE = "BALANCE"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class EntitlementKind(StrEnum):
    TIME_CREDIT = "TIME_CREDIT"
    PACKAGE_CREDIT = "PACKAGE_CREDIT"
    VIP = "VIP"


class EntitlementStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    CONNECTION_LOST = "CONNECTION_LOST"


class AgentCommandType(StrEnum):
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    MESSAGE = "MESSAGE"
    END_SESSION = "END_SESSION"
    SHUTDOWN = "SHUTDOWN"
    RESTART = "RESTART"
    SYNC = "SYNC"


class AgentCommandStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKED = "ACKED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
