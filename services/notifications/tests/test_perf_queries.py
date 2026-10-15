"""Perf regressions: inbox listing has a fixed query count and uses the owner/created index."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, text

from ff_notifications.domain.models import Alert, AlertMessage, AlertPayload, RuleKind
from ff_notifications.persistence.store import Store

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


async def _seed(n=200):
    st = Store("sqlite+aiosqlite:///:memory:")
    await st.create_all()
    for i in range(n):
        a = Alert(
            id=f"a{i:05d}", owner_id=f"o{i % 4}", watch_id=f"w{i}", rule=RuleKind.PRICE_DROP,
            message=AlertMessage("t", "t", "b", "b"), payload=AlertPayload(listing_ids=("l",)),
            fingerprint=f"f{i}", created_at=NOW - timedelta(minutes=i),
        )
        assert await st.insert_alert_once(a)
    return st


def test_list_alerts_fixed_query_count_and_order():
    async def go():
        st = await _seed(200)
        n = [0]
        bump = lambda *a: n.__setitem__(0, n[0] + 1)  # noqa: E731
        event.listen(st.engine.sync_engine, "before_cursor_execute", bump)
        items, total, unread = await st.list_alerts("o1", unread_only=False, offset=0, limit=50)
        assert n[0] <= 3, n[0]  # page + unread + total; never per-alert
        assert (len(items), total, unread) == (50, 50, 50)
        assert [a.created_at for a in items] == sorted((a.created_at for a in items), reverse=True)
        n[0] = 0
        await st.list_alerts("o1", unread_only=True, offset=0, limit=50)
        assert n[0] <= 2, n[0]

    asyncio.run(go())


def test_list_alerts_uses_owner_created_index_without_sort():
    async def go():
        st = await _seed(50)
        sql = (
            "EXPLAIN QUERY PLAN SELECT * FROM alerts WHERE owner_id='o1' "
            "ORDER BY created_at DESC, id DESC LIMIT 20"
        )
        async with st.engine.connect() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(sql))).all())
        assert "ix_alert_owner_created" in plan and "TEMP B-TREE" not in plan

    asyncio.run(go())


def test_retention_prune_uses_created_index():
    async def go():
        st = await _seed(50)
        async with st.engine.connect() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(
                "EXPLAIN QUERY PLAN DELETE FROM alerts WHERE created_at < '2026'"))).all())
        assert "ix_alert_created" in plan

    asyncio.run(go())
