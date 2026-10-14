"""Tracking provider interface. Real providers are stubs until licensed APIs are configured."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.models import CarrierRef, GeoPoint, TrackingSnapshot


class ProviderUnavailable(Exception):
    """The provider is disabled, not configured, or failed.

    ``reason`` is a short stable code (kill_switch, not_configured, blocked, rate_limited,
    upstream_error, timeout, bad_payload, cooldown, unsupported) safe to expose as a warning.
    """

    def __init__(self, message: str, *, reason: str = "unavailable") -> None:
        super().__init__(message)
        self.reason = reason


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


@dataclass(frozen=True, slots=True)
class VesselEta:
    """Vessel progress from an AIS provider (official API only): position + ETA, nothing else."""

    imo: str
    fetched_at: datetime
    eta: datetime | None = None
    destination_locode: str | None = None
    point: GeoPoint | None = None
    speed_knots: float | None = None
    vessel_name: str | None = None


class VesselEtaProvider(Protocol):
    id: str

    async def vessel_eta(self, imo: str, *, now: datetime) -> VesselEta | None: ...
