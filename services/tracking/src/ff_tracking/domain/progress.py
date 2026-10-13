"""Progress percentage derived from the normalized status."""

from __future__ import annotations

from ff_tracking.domain.enums import ShipmentStatus as S

PROGRESS: dict[S, int] = {
    S.BOOKED: 5, S.GATE_IN: 15, S.LOADED: 25, S.DEPARTED: 35, S.IN_TRANSIT: 55,
    S.TRANSSHIPMENT: 60, S.ARRIVED: 75, S.DISCHARGED: 80, S.CUSTOMS_HOLD: 85,
    S.RELEASED: 90, S.OUT_FOR_DELIVERY: 95, S.DELIVERED: 100,
}


def progress_percent(status: S, events: list | tuple = ()) -> int:
    """Exceptions keep the progress reached by the last non-exception event."""
    if status is S.EXCEPTION:
        for event in reversed(list(events)):
            if event.status is not S.EXCEPTION:
                return PROGRESS[event.status]
        return 0
    return PROGRESS[status]
