"""Signals data source interface."""

from typing import Protocol

from ff_trust.domain.signals import SupplierSignals


class AdapterDisabled(RuntimeError):
    """Raised by real adapters that are not enabled/configured."""


class SignalsAdapter(Protocol):
    name: str

    async def get_signals(self, supplier_id: str) -> SupplierSignals | None:
        """Signals for a supplier, or None if the supplier is unknown to this source."""
        ...
