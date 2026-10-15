from __future__ import annotations

from ff_payments.config import Settings
from ff_payments.providers.base import PaymentProvider
from ff_payments.providers.mock import MockProvider
from ff_payments.providers.usdt_tron import (
    ExplorerClient,
    ProviderNotConfigured,
    UsdtTronProvider,
    is_valid_tron_address,
)


def build_provider(settings: Settings) -> PaymentProvider | None:
    """None when FF_PAYMENTS_PROVIDER=off (default is mock; real chain providers are opt-in)."""
    name = settings.provider.strip().lower()
    if name == "mock":
        return MockProvider()
    if name == "usdt_tron":
        for label, val in (("FF_PAYMENTS_USDT_RECEIVE_ADDRESS", settings.usdt_receive_address),
                           ("FF_PAYMENTS_USDT_CONTRACT", settings.usdt_contract)):
            if val is not None and not is_valid_tron_address(val):
                raise ProviderNotConfigured(f"{label} is not a valid TRON base58check address", code="invalid_address")
        url = settings.usdt_explorer_url
        if url is not None and not url.lower().startswith("https://"):
            raise ProviderNotConfigured("FF_PAYMENTS_USDT_EXPLORER_URL must be https", code="invalid_explorer_url")
        explorer = (ExplorerClient(settings.usdt_explorer_url,
                                   settings.usdt_explorer_api_key.get_secret_value()
                                   if settings.usdt_explorer_api_key else None)
                    if settings.usdt_explorer_url else None)
        return UsdtTronProvider(address=settings.usdt_receive_address, contract=settings.usdt_contract,
                                explorer=explorer, min_confirmations=settings.usdt_min_confirmations)
    return None
