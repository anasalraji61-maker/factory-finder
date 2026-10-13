from datetime import UTC, datetime, timedelta

from ff_tracking.adapters.mock import MockProvider
from ff_tracking.domain.enums import ReferenceType as R
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.progress import progress_percent

ANCHOR = datetime(2026, 10, 1, tzinfo=UTC)


async def snap(ref, rt, days):
    return await MockProvider().track(ref, rt, None, anchor=ANCHOR, now=ANCHOR + timedelta(days=days))


async def test_deterministic():
    a, b = await snap("CSQU3054383", R.CONTAINER, 20), await snap("CSQU3054383", R.CONTAINER, 20)
    assert a == b
    c = await snap("MSCU6639870", R.CONTAINER, 20)
    assert [e.location.hub_id for e in a.events] != [e.location.hub_id for e in c.events] or a.vessel != c.vessel


async def test_progresses_with_time_and_prefix_stable():
    early, mid, late = [await snap("CSQU3054383", R.CONTAINER, d) for d in (0, 6, 120)]
    assert 1 <= len(early.events) < len(mid.events) < len(late.events)
    assert late.status is S.DELIVERED
    assert [e.id for e in early.events] == [e.id for e in late.events[: len(early.events)]]
    ts = [e.timestamp for e in late.events]
    assert ts == sorted(ts)
    assert progress_percent(late.status) == 100 and progress_percent(early.status) < 100
    assert late.eta and late.destination_hub_id and late.vessel and late.origin


async def test_air_has_flight_and_carrier():
    s = await snap("176-12345675", R.AWB, 30)
    assert s.flight and s.carrier.code == "emirates" and s.status is S.DELIVERED
    assert s.origin_hub_id in {"PVG", "CAN", "SZX"}


async def test_vessel_imo_uses_reference():
    s = await snap("9074729", R.VESSEL_IMO, 5)
    assert s.vessel.imo == "9074729"
