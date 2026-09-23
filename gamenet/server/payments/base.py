"""Payment provider interface (Master Spec 207).

Core sale logic talks only to this interface, so the system is never
locked to one card-terminal vendor. Real terminal adapters implement
these three methods later.
"""

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderTimeout(Exception):
    """No answer from the terminal: payment becomes UNKNOWN, never retried
    blindly (Master Spec 77)."""


class ProviderError(Exception):
    """Definitive provider failure."""


@dataclass
class ProviderResult:
    status: str  # PAID | PROCESSING | FAILED
    provider_ref: str | None = None
    message: str | None = None


class PaymentProvider(Protocol):
    name: str

    def start_payment(
        self, *, amount: int, reference: str, meta: dict[str, Any]
    ) -> ProviderResult: ...

    def check_status(
        self, *, provider_ref: str, meta: dict[str, Any]
    ) -> ProviderResult: ...
