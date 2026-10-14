from __future__ import annotations

from ff_payments.config import Settings
from ff_payments.providers.base import PaymentProvider
from ff_payments.providers.mock import MockProvider
from ff_payments.providers.usdt_tron import ExplorerClient, UsdtTronProvider


def build_provider(settings: Settings) -> PaymentProvider | None:
    """None when FF_PAYMENTS_PROVIDER=off (default is mock; real chain providers are opt-in)."""
    name = settings.provider.strip().lower()
    if name == "mock":
        return MockProvider()
    if name == "usdt_tron":
        explorer = (ExplorerClient(settings.usdt_explorer_url,
                                   settings.usdt_explorer_api_key.get_secret_value()
                                   if settings.usdt_explorer_api_key else None)
                    if settings.usdt_explorer_url else None)
        return UsdtTronProvider(address=settings.usdt_receive_address, contract=settings.usdt_contract,
                                explorer=explorer, min_confirmations=settings.usdt_min_confirmations)
    return None
