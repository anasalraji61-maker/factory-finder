"""Performance regressions: the batch endpoint costs a constant number of statements; indexes are used."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert, text

from ff_trust.adapters.mock import MockSignalsAdapter
from ff_trust.cache import TTLCache
from ff_trust.config import ScoringConfig
from ff_trust.db import Database, reports
from ff_trust.service import TrustService
from ff_trust.store import ReportStore, SnapshotStore


async def _svc(accepted_for=()):
    db = Database("sqlite+aiosqlite:///:memory:", True)
    await db.ensure()
    now = datetime.now(UTC)
    rows = [dict(id=f"r{i}", supplier_id=sid, reporter_id=f"u{i}", type="fraud", text="t", status="accepted",
                 created_at=now - timedelta(minutes=i), low_trust=False) for i, sid in enumerate(accepted_for)]
    if rows:
        async with db.begin() as c:
            await c.execute(insert(reports), rows)
    svc = TrustService(MockSignalsAdapter(), ScoringConfig(), TTLCache(300, 1000),
                       snapshots=SnapshotStore(db), reports=ReportStore(db=db))
    n = [0]
    event.listen(db.engine.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))
    return db, svc, n


def test_batch_cold_is_constant_statements_and_matches_single():
    async def go():
        ids = [f"sup{i}" for i in range(50)]
        db, svc, n = await _svc(accepted_for=["sup3", "sup3", "sup7"])
        n[0] = 0
        batch = await svc.for_suppliers(ids)
        assert n[0] <= 10, n[0]  # was ~6 per supplier (303 for 50)
        assert [b.supplier_id for b in batch] == ids
        n[0] = 0
        await svc.for_suppliers(ids)
        assert n[0] == 0  # warm: cache only
        _, svc2, _ = await _svc(accepted_for=["sup3", "sup3", "sup7"])
        single = [await svc2.for_supplier(i) for i in ids]
        assert [(b.supplier_id, b.score, b.band) for b in batch] == [(s.supplier_id, s.score, s.band) for s in single]
        # snapshot history was recorded once per supplier, and an unchanged re-score does not duplicate it
        assert len(await svc.snapshots.list("sup3")) == 1
        svc.cache.delete("sup3")
        await svc.for_suppliers(["sup3"])
        assert len(await svc.snapshots.list("sup3")) == 1
        await db.dispose()

    asyncio.run(go())


def test_low_trust_count_and_snapshot_lookup_use_indexes():
    async def go():
        db, _, _ = await _svc()
        async with db.begin() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(
                "explain query plan select count(*) from reports where low_trust is 1"))).all())
            assert "ix_reports_lowtrust_status_created" in plan and "COVERING" in plan, plan
            plan = " ".join(str(r) for r in (await c.execute(text(
                "explain query plan select score from score_snapshots where supplier_id='x' order by at desc, id desc limit 1"))).all())
            assert "ix_score_snapshots_supplier_at" in plan, plan
        await db.dispose()

    asyncio.run(go())
