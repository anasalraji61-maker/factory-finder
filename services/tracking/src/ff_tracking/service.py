"""Application service: shipments per user, refresh with throttling."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from ff_tracking.adapters.base import ProviderUnavailable, TrackingProvider
from ff_tracking.domain.carriers import find_carrier
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.errors import (
    Conflict,
    DomainError,
    InvalidReference,
    NotFound,
    RefreshThrottled,
)
from ff_tracking.domain.models import CarrierRef, Shipment
from ff_tracking.domain.validators import validate_reference
from ff_tracking.repository import ShipmentRepository


class ProviderFailed(DomainError):
    status_code = 502
    default_code = "provider_unavailable"


def detect_carrier(reference_type: ReferenceType, prefix: str | None, typed: str | None) -> CarrierRef | None:
    from ff_tracking.domain import carriers as c

    if typed:
        found = find_carrier(typed, reference_type.mode)
        return found.ref() if found else CarrierRef(name=typed.strip())
    if not prefix:
        return None
    found = {
        ReferenceType.CONTAINER: c.carrier_for_container_owner,
        ReferenceType.BL: c.carrier_for_bl_prefix,
        ReferenceType.AWB: c.carrier_for_awb_prefix,
    }.get(reference_type, lambda _: None)(prefix)
    return found.ref() if found else None


class ShipmentService:
    def __init__(self, repo: ShipmentRepository, provider: TrackingProvider, clock: Callable[[], datetime],
                 min_interval_seconds: int) -> None:
        self.repo, self.provider, self.clock = repo, provider, clock
        self.min_interval = timedelta(seconds=min_interval_seconds)

    async def create(self, owner_id: str, reference: str, reference_type: ReferenceType,
                     carrier: str | None, label: str | None) -> Shipment:
        v = validate_reference(reference_type, reference)
        if not v.valid:
            raise InvalidReference(f"Invalid {reference_type.value} reference", details={
                "reference": reference, "reason": v.reason})
        if await self.repo.find_by_reference(owner_id, reference_type.value, v.normalized):
            raise Conflict("This reference is already tracked", code="duplicate_shipment")
        now = self.clock()
        sh = Shipment(id=f"shp_{uuid.uuid4().hex}", owner_id=owner_id, reference=v.normalized,
                      reference_type=reference_type, carrier=detect_carrier(reference_type, v.prefix, carrier),
                      label=label, created_at=now, updated_at=now)
        await self._fetch(sh, now, anchor=now)
        await self.repo.save(sh)
        return sh

    async def _fetch(self, sh: Shipment, now: datetime, anchor: datetime) -> None:
        try:
            snap = await self.provider.track(sh.reference, sh.reference_type, sh.carrier, anchor=anchor, now=now)
        except ProviderUnavailable as exc:
            raise ProviderFailed(str(exc)) from exc
        sh.apply_snapshot(snap, now)

    async def get(self, owner_id: str, shipment_id: str) -> Shipment:
        sh = await self.repo.get(shipment_id)
        if sh is None or sh.owner_id != owner_id:  # do not leak other users' ids
            raise NotFound("Shipment not found")
        return sh

    async def refresh(self, owner_id: str, shipment_id: str) -> Shipment:
        sh = await self.get(owner_id, shipment_id)
        now = self.clock()
        last = sh.last_refresh_attempt_at or sh.last_refreshed_at
        if last is not None and now - last < self.min_interval:
            wait = int((self.min_interval - (now - last)).total_seconds()) + 1
            raise RefreshThrottled(wait)
        sh.last_refresh_attempt_at = now
        await self._fetch(sh, now, anchor=sh.created_at)
        await self.repo.save(sh)
        return sh

    async def delete(self, owner_id: str, shipment_id: str) -> None:
        await self.get(owner_id, shipment_id)
        await self.repo.delete(shipment_id)

    async def list(self, owner_id: str, status: str | None, page: int, page_size: int):
        return await self.repo.list(owner_id, status=status, page=page, page_size=page_size)
