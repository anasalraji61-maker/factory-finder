"""Performance regressions: refresh job and list use indexes and bounded work."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, text

from ff_tracking.domain.models import ReferenceType, Shipment
from ff_tracking.jobs import RefreshJob
from ff_tracking.repository import ShipmentRepository, make_engine

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


async def _repo(n=1500):
    e = make_engine("sqlite+aiosqlite:///:memory:")
    repo = ShipmentRepository(e)
    await repo.create_tables()
    for i in range(n):
        recent = i % 3 != 0  # two thirds refreshed an hour ago (not due), one third never refreshed
        sh = Shipment(id=f"shp_{i:05d}", owner_id=f"u{i % 10}", reference=f"MSKU{i:07d}", reference_type=ReferenceType.CONTAINER,
                      last_refreshed_at=NOW - timedelta(hours=1) if recent else None,
                      created_at=NOW - timedelta(minutes=i), updated_at=NOW)
        if i % 10 == 9:
            sh.status = "delivered"
        await repo.save(sh, create=True)
    return e, repo


def test_due_for_refresh_reads_only_a_batch_via_index():
    async def go():
        e, repo = await _repo()
        n = [0]
        event.listen(e.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))

        class Svc:
            calls = 0

            async def refresh_system(self, sh):
                Svc.calls += 1
                return 0

        job = RefreshJob(repo, Svc(), lambda: NOW, interval_hours=6, batch_size=25)
        n[0] = 0
        stats = await job.run_once()
        assert n[0] == 1 and stats["refreshed"] == 25 and Svc.calls == 25  # one bounded query
        due = await repo.due_for_refresh(NOW - timedelta(hours=6), 10_000)
        assert all(s.status != "delivered" and s.last_refreshed_at is None for s in due)
        async with e.connect() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(
                "explain query plan select * from shipments where refresh_marker <= '2026-10-01' "
                "order by refresh_marker, created_at limit 25"))).all())
        assert "ix_shipments_refresh" in plan and "TEMP B-TREE" not in plan, plan

    asyncio.run(go())


def test_list_page_uses_owner_created_index_without_sort():
    async def go():
        e, repo = await _repo(300)
        async with e.connect() as c:
            await c.execute(text("analyze"))
            plan = " ".join(str(r) for r in (await c.execute(text(
                "explain query plan select * from shipments where owner_id='u1' order by created_at desc, id limit 20"))).all())
        assert "ix_shipments_owner_created" in plan, plan
        n = [0]
        event.listen(e.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))
        items, total = await repo.list("u1", status=None, page=1, page_size=20)
        assert n[0] == 2 and len(items) == 20 and total == 30  # count + page, no per-row queries

    asyncio.run(go())
