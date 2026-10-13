"""Stubs for real tracking providers (licensed APIs only; never scrape carrier sites, CLAUDE.md rule 6)."""

from __future__ import annotations

from datetime import datetime

from ff_tracking.adapters.base import ProviderUnavailable
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.models import CarrierRef, TrackingSnapshot


class LicensedProviderStub:
    """Placeholder for a licensed aggregator (e.g. a container/air tracking API). Not implemented."""

    def __init__(self, provider_id: str, api_key: str | None = None) -> None:
        self.id = provider_id
        self._api_key = api_key

    async def track(
        self, reference: str, reference_type: ReferenceType, carrier: CarrierRef | None,
        *, anchor: datetime, now: datetime,
    ) -> TrackingSnapshot:
        if not self._api_key:
            raise ProviderUnavailable(f"provider '{self.id}' has no API key configured")
        raise ProviderUnavailable(f"provider '{self.id}' is not implemented yet")
