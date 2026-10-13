"""Tracking provider interface. Real providers are stubs until licensed APIs are configured."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.models import CarrierRef, TrackingSnapshot


class ProviderUnavailable(Exception):
    """The provider is disabled, not configured, or failed."""


class TrackingProvider(Protocol):
    id: str

    async def track(
        self,
        reference: str,
        reference_type: ReferenceType,
        carrier: CarrierRef | None,
        *,
        anchor: datetime,
        now: datetime,
    ) -> TrackingSnapshot:
        """Return everything known about ``reference`` at ``now``.

        ``anchor`` is when the shipment was first registered; providers that fabricate data
        (the mock) use it as a stable time base.
        """
        ...
