"""Manual provider: the operator already ran the physical terminal
(or took cash); the API only records the payment with its reference
(Master Spec 208)."""

from typing import Any

from gamenet.server.payments.base import ProviderResult


class ManualProvider:
    name = "manual"

    def start_payment(
        self, *, amount: int, reference: str, meta: dict[str, Any]
    ) -> ProviderResult:
        return ProviderResult(
            status="PAID",
            provider_ref=(meta or {}).get("provider_ref"),
            message="manual: recorded by operator",
        )

    def check_status(
        self, *, provider_ref: str, meta: dict[str, Any]
    ) -> ProviderResult:
        return ProviderResult(
            status="PAID", provider_ref=provider_ref,
            message="manual: assumed settled",
        )
