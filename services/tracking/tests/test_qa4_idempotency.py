# ruff: noqa: E501
"""QA pass 4: duplicate refreshes across workers, throttle races, refresh-vs-delete resurrection."""

import asyncio

import pytest
from conftest import Clock

from ff_tracking.adapters.mock import MockProvider
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.errors import NotFound, RefreshThrottled
from ff_tracking.domain.validators import container_check_digit
from ff_tracking.jobs import RefreshJob
from ff_tracking.repository import ShipmentRepository, make_engine
from ff_tracking.service import ShipmentService


def _ref():
    base = "MSKU000000"
    return base + str(container_check_digit(base))


class Counting:
    id = "counting"

    def __init__(self, delay=0.01):
        self.n, self.inner, self.delay = 0, MockProvider(), delay

    async def track(self, *a, **kw):
        self.n += 1
        await asyncio.sleep(self.delay)
        return await self.inner.track(*a, **kw)


async def make(tmp_path):
    repo = ShipmentRepository(make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db"))
    await repo.create_tables()
    clock = Clock()
    svc = ShipmentService(repo, MockProvider(), clock, 60, 200)
    sh = await svc.create("u1", _ref(), ReferenceType.CONTAINER, None, None)
    return repo, svc, clock, sh


async def test_concurrent_user_refreshes_hit_provider_once(tmp_path):
    repo, svc, clock, sh = await make(tmp_path)
    prov = svc.provider = Counting()
    clock.advance(minutes=5)
    res = await asyncio.gather(*(svc.refresh("u1", sh.id) for _ in range(5)), return_exceptions=True)
    assert prov.n == 1
    assert sum(not isinstance(r, Exception) for r in res) == 1
    assert all(isinstance(r, RefreshThrottled) for r in res if isinstance(r, Exception))


async def test_two_workers_refresh_each_shipment_once(tmp_path):
    repo, svc, clock, sh = await make(tmp_path)
    prov = svc.provider = Counting()
    clock.advance(hours=7)
    jobs = [RefreshJob(repo, svc, clock, interval_hours=6) for _ in range(3)]  # separate workers, separate locks
    await asyncio.gather(*(j.run_once() for j in jobs))
    assert prov.n == 1


async def test_refresh_does_not_resurrect_deleted_shipment(tmp_path):
    repo, svc, clock, sh = await make(tmp_path)
    svc.provider = Counting(delay=0.05)
    clock.advance(hours=7)
    job = RefreshJob(repo, svc, clock, interval_hours=6)
    t = asyncio.create_task(job.run_once())
    await asyncio.sleep(0.01)
    await svc.delete("u1", sh.id)
    await t
    assert await repo.get(sh.id) is None
    assert await repo.count_for_owner("u1") == 0


async def test_user_refresh_of_concurrently_deleted_shipment_is_not_found(tmp_path):
    repo, svc, clock, sh = await make(tmp_path)
    svc.provider = Counting(delay=0.05)
    clock.advance(minutes=5)
    t = asyncio.create_task(svc.refresh("u1", sh.id))
    await asyncio.sleep(0.01)
    await svc.delete("u1", sh.id)
    with pytest.raises(NotFound):
        await t
    assert await repo.get(sh.id) is None
