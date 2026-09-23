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


class PricingKind(StrEnum):
    PER_HOUR = "PER_HOUR"
    FLAT = "FLAT"
    MULTIPLIER = "MULTIPLIER"


class PricingScope(StrEnum):
    ANY = "ANY"
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"
