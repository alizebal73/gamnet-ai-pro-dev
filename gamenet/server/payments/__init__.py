from gamenet.server.payments.base import (
    PaymentProvider,
    ProviderError,
    ProviderResult,
    ProviderTimeout,
)
from gamenet.server.payments.manual import ManualProvider
from gamenet.server.payments.mock import MockProvider

PROVIDERS: dict[str, PaymentProvider] = {
    "mock": MockProvider(),
    "manual": ManualProvider(),
}


def get_provider(name: str) -> PaymentProvider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(f"unknown payment provider: {name}")


__all__ = [
    "PaymentProvider",
    "ProviderError",
    "ProviderResult",
    "ProviderTimeout",
    "ManualProvider",
    "MockProvider",
    "get_provider",
]
