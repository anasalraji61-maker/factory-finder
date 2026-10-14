"""Provider composition: route by reference type, add vessel ETA, degrade to the mock with a warning."""

from __future__ import annotations

from datetime import datetime

from ff_tracking.adapters.base import (
    ProviderUnavailable,
    TrackingProvider,
    VesselEtaProvider,
)
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.models import CarrierRef, TrackingEvent, TrackingSnapshot, VesselRef
from ff_tracking.domain.normalize import DESC_AR, DESC_EN, location_of, resolve_location


class RoutingProvider:
    """container/B/L -> container provider, AWB -> air provider, vessel IMO -> AIS provider."""

    id = "http"

    def __init__(self, container: TrackingProvider | None = None, awb: TrackingProvider | None = None,
                 vessel: VesselEtaProvider | None = None) -> None:
        self.container, self.awb, self.vessel = container, awb, vessel

    async def track(self, reference: str, reference_type: ReferenceType, carrier: CarrierRef | None,
                    *, anchor: datetime, now: datetime) -> TrackingSnapshot:
        if reference_type is ReferenceType.VESSEL_IMO:
            return await self._vessel_only(reference, now)
        target = self.awb if reference_type is ReferenceType.AWB else self.container
        if target is None:
            raise ProviderUnavailable("no provider for this reference type", reason="not_configured")
        snap = await target.track(reference, reference_type, carrier, anchor=anchor, now=now)
        imo = snap.vessel.imo if snap.vessel else None
        if snap.eta is None and imo and self.vessel is not None:
            try:  # ETA is an optional enrichment: its failure must not fail the shipment
                v = await self.vessel.vessel_eta(imo, now=now)
            except ProviderUnavailable:
                v = None
            if v and v.eta:
                snap = replace_snapshot(snap, eta=v.eta)
        return snap

    async def _vessel_only(self, imo: str, now: datetime) -> TrackingSnapshot:
        if self.vessel is None:
            raise ProviderUnavailable("no vessel provider", reason="not_configured")
        v = await self.vessel.vessel_eta(imo, now=now)
        if v is None:
            raise ProviderUnavailable("vessel not found", reason="bad_payload")
        loc = resolve_location(v.destination_locode) if v.destination_locode else None
        event = TrackingEvent(
            id=f"evt_ais_{imo}_{int(v.fetched_at.timestamp())}", status=S.IN_TRANSIT,
            description=DESC_EN[S.IN_TRANSIT], description_ar=DESC_AR[S.IN_TRANSIT],
            location=resolve_location(None, "At sea", None, v.point.lat, v.point.lon) if v.point else None,
            timestamp=v.fetched_at, vessel=VesselRef(name=v.vessel_name or f"IMO {imo}", imo=imo),
            source=self.vessel.id)
        return TrackingSnapshot(
            provider=self.vessel.id, fetched_at=now, events=(event,), eta=v.eta,
            destination=location_of(v.destination_locode),
            destination_hub_id=loc.hub_id if loc else None,
            vessel=VesselRef(name=v.vessel_name or f"IMO {imo}", imo=imo))


def replace_snapshot(snap: TrackingSnapshot, **kw) -> TrackingSnapshot:
    return snap.model_copy(update=kw)


class FallbackProvider:
    """Try ``primary``; on ProviderUnavailable return ``fallback`` data tagged with a warning."""

    def __init__(self, primary: TrackingProvider, fallback: TrackingProvider) -> None:
        self.primary, self.fallback = primary, fallback
        self.id = primary.id

    async def track(self, reference: str, reference_type: ReferenceType, carrier: CarrierRef | None,
                    *, anchor: datetime, now: datetime) -> TrackingSnapshot:
        try:
            return await self.primary.track(reference, reference_type, carrier, anchor=anchor, now=now)
        except ProviderUnavailable as exc:
            snap = await self.fallback.track(reference, reference_type, carrier, anchor=anchor, now=now)
            return snap.model_copy(update={"warning": f"provider_unavailable:{exc.reason}"})


__all__ = ["FallbackProvider", "RoutingProvider", "replace_snapshot"]
