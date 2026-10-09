"""Enumerations shared by the whole tracking domain."""

from __future__ import annotations

from enum import StrEnum


class TransportMode(StrEnum):
    SEA = "sea"
    AIR = "air"


class ReferenceType(StrEnum):
    CONTAINER = "container"
    BL = "bl"
    AWB = "awb"
    VESSEL_IMO = "vessel_imo"

    @property
    def mode(self) -> TransportMode:
        return TransportMode.AIR if self is ReferenceType.AWB else TransportMode.SEA


class ShipmentStatus(StrEnum):
    """Normalized status vocabulary every provider adapter maps onto."""

    BOOKED = "booked"
    GATE_IN = "gate_in"
    LOADED = "loaded"
    DEPARTED = "departed"
    IN_TRANSIT = "in_transit"
    TRANSSHIPMENT = "transshipment"
    ARRIVED = "arrived"
    DISCHARGED = "discharged"
    CUSTOMS_HOLD = "customs_hold"
    RELEASED = "released"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
