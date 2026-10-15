"""ETA recompute and delay flag (pure functions)."""

from __future__ import annotations

from datetime import datetime, timedelta

from ff_tracking.domain.enums import ShipmentStatus as S

DELAY_TOLERANCE = timedelta(hours=12)
STALE_ETA_REPLAN = timedelta(hours=24)
_LANDED = {S.ARRIVED, S.DISCHARGED, S.CUSTOMS_HOLD, S.RELEASED, S.OUT_FOR_DELIVERY, S.DELIVERED}


def assess_eta(
    eta: datetime | None, initial_eta: datetime | None, status: S, now: datetime,
    actual_arrival: datetime | None = None,
) -> tuple[datetime | None, datetime | None, bool, int | None]:
    """Return ``(eta, initial_eta, delayed, delay_hours)``.

    * ``initial_eta`` is the first ETA ever seen and is never changed afterwards.
    * delayed when the current ETA slipped more than 12 h past the initial one.
    * ``actual_arrival`` (landed cargo at the destination) replaces the ETA in the slip test.
    * an ETA already in the past while the cargo has not landed is stale: it is recomputed as
      now + 24 h (an estimate) and the shipment is flagged delayed.
    """
    if eta is None:
        return None, initial_eta, False, None
    if initial_eta is None:
        initial_eta = eta
    if actual_arrival is not None and status in _LANDED:
        # the cargo is here: judge against what really happened, not against the (now moot) estimate
        slip = actual_arrival - initial_eta
        late = slip > DELAY_TOLERANCE
        return eta, initial_eta, late, int(slip.total_seconds() // 3600) if late else None
    if status not in _LANDED and eta < now - DELAY_TOLERANCE:
        late = now - initial_eta
        return now + STALE_ETA_REPLAN, initial_eta, True, max(int(late.total_seconds() // 3600), 0)
    slip = eta - initial_eta
    if slip > DELAY_TOLERANCE:
        return eta, initial_eta, True, int(slip.total_seconds() // 3600)
    return eta, initial_eta, False, None
