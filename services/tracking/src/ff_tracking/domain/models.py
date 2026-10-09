"""Domain value objects and the Shipment aggregate (pure data, no I/O).

These Pydantic models are JSON-shaped on purpose: the API layer reuses the value
objects directly so the wire format and the domain cannot drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ff_tracking.domain.enums import ReferenceType, ShipmentStatus, TransportMode


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime; naive values are interpreted as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeoPoint(_Value):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Location(_Value):
    """Same shape as common.schema.json#/$defs/Location."""

    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    city: str | None = None
    point: GeoPoint | None = None


class EventLocation(_Value):
    """Where an event happened: a hub (port/airport), a city, or a sea area."""

    name: str
    name_ar: str | None = None
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    hub_id: str | None = Field(default=None, description="UN/LOCODE (sea port) or IATA (airport)")
    point: GeoPoint | None = None


class VesselRef(_Value):
    name: str
    imo: str | None = Field(default=None, pattern=r"^[0-9]{7}$")
    voyage: str | None = None


class FlightRef(_Value):
    number: str
    carrier_code: str | None = Field(default=None, description="IATA airline designator")


class CarrierRef(_Value):
    code: str | None = Field(default=None, description="Stable carrier id; null for a user-typed unknown carrier")
    name: str
    name_ar: str | None = None
    scac: str | None = None
    iata_code: str | None = None
    awb_prefix: str | None = None


class TrackingEvent(_Value):
    id: str
    status: ShipmentStatus
    description: str
    description_ar: str
    location: EventLocation | None = None
    timestamp: UtcDatetime
    vessel: VesselRef | None = None
    flight: FlightRef | None = None
    source: str = Field(description="Provider adapter id that reported the event")


class TrackingSnapshot(_Value):
    """Everything a provider knows about a reference at ``fetched_at``."""

    provider: str
    fetched_at: UtcDatetime
    events: tuple[TrackingEvent, ...] = ()
    eta: UtcDatetime | None = None
    origin: Location | None = None
    origin_hub_id: str | None = None
    destination: Location | None = None
    destination_hub_id: str | None = None
    vessel: VesselRef | None = None
    flight: FlightRef | None = None
    carrier: CarrierRef | None = None

    @property
    def status(self) -> ShipmentStatus | None:
        return self.events[-1].status if self.events else None


class Shipment(BaseModel):
    """The tracked-shipment aggregate owned by one user."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    owner_id: str
    reference: str
    reference_type: ReferenceType
    carrier: CarrierRef | None = None
    label: str | None = None
    status: ShipmentStatus = ShipmentStatus.BOOKED
    eta: UtcDatetime | None = None
    origin: Location | None = None
    origin_hub_id: str | None = None
    destination: Location | None = None
    destination_hub_id: str | None = None
    vessel: VesselRef | None = None
    flight: FlightRef | None = None
    events: list[TrackingEvent] = Field(default_factory=list)
    provider: str | None = None
    last_refreshed_at: UtcDatetime | None = None
    last_refresh_attempt_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @property
    def mode(self) -> TransportMode:
        return self.reference_type.mode

    @property
    def last_event(self) -> TrackingEvent | None:
        return self.events[-1] if self.events else None

    def apply_snapshot(self, snapshot: TrackingSnapshot, now: datetime) -> None:
        """Merge provider data into the aggregate (provider is the source of truth for events)."""
        events = sorted(snapshot.events, key=lambda e: e.timestamp)
        if events:
            self.events = events
            self.status = events[-1].status
        self.eta = snapshot.eta if snapshot.eta is not None else self.eta
        self.origin = snapshot.origin or self.origin
        self.origin_hub_id = snapshot.origin_hub_id or self.origin_hub_id
        self.destination = snapshot.destination or self.destination
        self.destination_hub_id = snapshot.destination_hub_id or self.destination_hub_id
        self.vessel = snapshot.vessel or self.vessel
        self.flight = snapshot.flight or self.flight
        if self.carrier is None and snapshot.carrier is not None:
            self.carrier = snapshot.carrier
        self.provider = snapshot.provider
        self.last_refreshed_at = now
        self.updated_at = now
