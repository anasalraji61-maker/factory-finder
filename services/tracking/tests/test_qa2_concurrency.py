# ruff: noqa: E501, SIM105
"""QA pass 2: concurrency / idempotency / error isolation on a file-backed SQLite database."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from conftest import Clock

from ff_tracking.adapters.base import ProviderUnavailable
from ff_tracking.adapters.mock import MockProvider
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.jobs import RefreshJob
from ff_tracking.relay import MockNotifyClient, OutboxRelay
from ff_tracking.repository import ShipmentRepository, make_engine
from ff_tracking.service import ShipmentService

REF = "MSKU0000006"  # check digit verified below via validator fallback


def _ref():
    from ff_tracking.domain.validators import container_check_digit
    base = "MSKU000000"
    return base + str(container_check_digit(base))


async def make(tmp_path, provider=None):
    repo = ShipmentRepository(make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db"))
    await repo.create_tables()
    clock = Clock()
    svc = ShipmentService(repo, provider or MockProvider(), clock, 60, 200)
    return repo, svc, clock


async def test_concurrent_duplicate_create_yields_one_shipment(tmp_path):
    repo, svc, _ = await make(tmp_path)
    res = await asyncio.gather(*(svc.create("u1", _ref(), ReferenceType.CONTAINER, None, None) for _ in range(6)),
                               return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    assert len(ok) == 1 and await repo.count_for_owner("u1") == 1
    assert all(getattr(r, "default_code", "") == "duplicate_shipment" or getattr(r, "code", "") == "duplicate_shipment"
               for r in res if isinstance(r, Exception)), res


async def test_outbox_add_is_idempotent_under_concurrency(tmp_path):
    repo, _, clock = await make(tmp_path)
    res = await asyncio.gather(*(repo.add_outbox(dedupe_key="k", shipment_id="s", owner_id="u", kind="x",
                                                 payload="{}", created_at=clock()) for _ in range(8)))
    assert sum(res) == 1


class Flaky:
    id = "flaky"

    def __init__(self, inner, bad_refs, exc):
        self.inner, self.bad, self.exc = inner, bad_refs, exc

    async def track(self, reference, *a, **kw):
        if reference in self.bad:
            raise self.exc
        return await self.inner.track(reference, *a, **kw)


async def test_job_isolates_provider_and_unexpected_failures(tmp_path):
    from ff_tracking.domain.validators import container_check_digit
    refs = []
    for i in range(3):
        b = f"MSKU00000{i}"
        refs.append(b + str(container_check_digit(b)))
    repo, svc, clock = await make(tmp_path)
    for r in refs:
        await svc.create("u1", r, ReferenceType.CONTAINER, None, None)
    svc.provider = Flaky(MockProvider(), {refs[0]: ProviderUnavailable("x", reason="timeout")}, None)
    svc.provider.exc = ProviderUnavailable("x", reason="timeout")
    clock.advance(hours=7)
    job = RefreshJob(repo, svc, clock, interval_hours=6, batch_size=10)
    st = await job.run_once()
    assert st["failed"] == 1 and st["refreshed"] == 2
    # unexpected exception type for one shipment must not abort the rest
    svc.provider = Flaky(MockProvider(), {refs[1]: RuntimeError("boom")}, RuntimeError("boom"))
    clock.advance(hours=7)
    st = await job.run_once()
    assert st["failed"] == 1 and st["refreshed"] == 2
    # failed attempt is remembered: no hammering inside the interval
    clock.advance(hours=1)
    assert (await job.run_once()) == {"refreshed": 0, "failed": 0, "events": 0}


async def test_concurrent_job_runs_refresh_each_shipment_once(tmp_path):
    repo, svc, clock = await make(tmp_path)
    await svc.create("u1", _ref(), ReferenceType.CONTAINER, None, None)
    calls = {"n": 0}
    inner = MockProvider()

    class Counting:
        id = "c"

        async def track(self, *a, **kw):
            calls["n"] += 1
            await asyncio.sleep(0.01)
            return await inner.track(*a, **kw)

    svc.provider = Counting()
    clock.advance(hours=7)
    job = RefreshJob(repo, svc, clock, interval_hours=6)
    await asyncio.gather(*(job.run_once() for _ in range(4)))
    assert calls["n"] == 1


async def test_run_forever_survives_cycle_errors_and_never_spins(tmp_path, monkeypatch):
    repo, svc, clock = await make(tmp_path)
    job = RefreshJob(repo, svc, clock)
    n = {"c": 0}
    sleeps = []

    async def boom():
        n["c"] += 1
        raise RuntimeError("x")

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    job._run_once = boom
    monkeypatch.setattr("ff_tracking.jobs.asyncio.sleep", fake_sleep)
    try:
        await job.run_forever(0)
    except asyncio.CancelledError:
        pass
    assert n["c"] == 3 and min(sleeps) >= 1.0


async def test_relay_backoff_concurrency_retention_and_tz(tmp_path):
    repo, _, clock = await make(tmp_path)
    for i in range(3):
        await repo.add_outbox(dedupe_key=f"k{i}", shipment_id="s", owner_id="u", kind="x",
                              payload=json.dumps({}), created_at=clock())
    client = MockNotifyClient()
    relay = OutboxRelay(repo, client, clock, retention_days=1)
    await asyncio.gather(*(relay.run_once() for _ in range(4)))
    assert sum(len(c) for c in client.calls) == 3  # each row sent exactly once

    # client crash (non-NotifyUnavailable) backs rows off instead of retrying every cycle
    await repo.add_outbox(dedupe_key="z", shipment_id="s", owner_id="u", kind="x", payload="{}", created_at=clock())

    class Crash:
        async def send(self, events):
            raise RuntimeError("bug")

    r2 = OutboxRelay(repo, Crash(), clock)
    assert (await r2.run_once())["retried"] == 1
    assert (await r2.run_once())["sent"] == 0  # inside backoff window
    stats = await repo.outbox_stats()
    assert stats["oldest_pending_at"].endswith("+00:00")  # tz-aware UTC, not naive
    # retention: delivered rows older than the window are purged, pending kept
    clock.now += timedelta(days=2)
    relay._purged_at = None
    await relay.run_once()
    st = await repo.outbox_stats()
    assert st["delivered"] == 1 and st["pending"] == 0  # old delivered purged; z delivered after backoff
    assert isinstance(clock.now, datetime) and clock.now.tzinfo is UTC
