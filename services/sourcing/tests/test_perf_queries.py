"""Performance regressions: public native search window uses an index and resolves suppliers concurrently."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert, text

from ff_sourcing.adapters.native import NativeAdapter, NativeStore
from ff_sourcing.db import NativeListingRow, make_engine
from ff_sourcing.domain.models import SearchQuery

NOW = datetime(2026, 10, 1, tzinfo=UTC)


async def _seed(n=600):
    e = make_engine("sqlite+aiosqlite:///:memory:")
    st = NativeStore(e)
    await st.ensure_ready()
    kinds = ["product", "raw_material", "production_line"]
    rows = [dict(id=f"nat_{i:08d}", supplier_id=f"sup{i % 40}", status="published" if i % 5 else "draft",
                 kind=kinds[i % 3], condition="new" if i % 2 else "used", title=f"Pump {i}", category="pumps",
                 price_min="1", price_max="2", currency="USD", unit="piece", moq=1, images=[],
                 origin={"country_code": "CN"}, specs={}, created_at=NOW, updated_at=NOW,
                 published_at=NOW - timedelta(minutes=i)) for i in range(n)]
    async with e.begin() as c:
        await c.execute(insert(NativeListingRow.__table__), rows)
        await c.execute(text("analyze"))
    return e, st


def test_published_window_uses_index_and_pushes_filters_down():
    async def go():
        e, st = await _seed()
        async with e.connect() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(
                "explain query plan select * from native_listings where status='published' "
                "order by published_at desc, id limit 200"))).all())
        assert "ix_native_listings_status_published" in plan or "ix_native_listings_status_kind_published" in plan, plan
        n = [0]
        event.listen(e.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))
        rows = await st.published(50, kind="raw_material", condition="used")
        assert n[0] == 1 and rows and all(r.kind == "raw_material" and r.condition == "used" for r in rows)
        assert [r.published_at for r in rows] == sorted((r.published_at for r in rows), reverse=True)

    asyncio.run(go())


def test_search_resolves_each_supplier_once_and_concurrently():
    async def go():
        _, st = await _seed()
        ad = NativeAdapter(st)
        state = {"calls": 0, "cur": 0, "peak": 0}

        async def resolver(sid):
            state["calls"] += 1
            state["cur"] += 1
            state["peak"] = max(state["peak"], state["cur"])
            await asyncio.sleep(0.005)
            state["cur"] -= 1
            return None

        ad.resolver = resolver
        out = await ad.search(SearchQuery(limit=200))
        assert len(out) == 200 and state["calls"] == len({d.supplier.id for d in out})  # one lookup per distinct supplier
        assert 1 < state["peak"] <= 8

    asyncio.run(go())
