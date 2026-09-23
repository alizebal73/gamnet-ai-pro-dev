"""Deterministic mock terminal for development and tests.

``meta.simulate`` controls behavior:
- absent: approve (PROCESSING then PAID on inquiry)
- "decline": decline immediately
- "timeout" / "timeout-then-paid" / "timeout-then-failed": no answer at
  charge time (payment becomes UNKNOWN); later inquiry resolves to
  PAID ("timeout", "timeout-then-paid") or FAILED ("timeout-then-failed").
"""

import uuid
from typing import Any

from gamenet.server.payments.base import ProviderResult, ProviderTimeout


class MockProvider:
    name = "mock"

    def start_payment(
        self, *, amount: int, reference: str, meta: dict[str, Any]
    ) -> ProviderResult:
        sim = (meta or {}).get("simulate")
        if sim in ("timeout", "timeout-then-paid", "timeout-then-failed"):
            raise ProviderTimeout("mock: no response from terminal")
        if sim == "decline":
            return ProviderResult(
                status="FAILED",
                provider_ref=f"MOCK-{uuid.uuid4().hex[:8]}",
                message="mock: declined",
            )
        return ProviderResult(
            status="PROCESSING",
            provider_ref=f"MOCK-{uuid.uuid4().hex[:8]}",
            message="mock: processing",
        )

    def check_status(
        self, *, provider_ref: str, meta: dict[str, Any]
    ) -> ProviderResult:
        if (meta or {}).get("simulate") == "timeout-then-failed":
            return ProviderResult(
                status="FAILED", provider_ref=provider_ref,
                message="mock: inquiry says failed",
            )
        return ProviderResult(
            status="PAID", provider_ref=provider_ref, message="mock: approved"
        )
