"""Performance regressions: bounded query counts for sweep / list, and the new indexes are used."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert

from ff_rfq.config import Settings
from ff_rfq.db import OfferRow, RequestInviteRow, RequestRow, make_engine
from ff_rfq.service import RfqService

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _req(i, **kw):
    d = dict(id=f"r{i:05d}", owner_id="owner", kind="product", title="t", quantity="1", unit="piece",
             condition="new", visibility="public", status="open", attachments=[], deadline=None,
             created_at=NOW - timedelta(minutes=i), updated_at=NOW)
    d.update(kw)
    return d


def _offer(i, rid, **kw):
    d = dict(id=f"o{i:05d}", request_id=rid, supplier_user_id="s", supplier_name="n", price_amount="1",
             price_currency="USD", status="active", valid_until=None, created_at=NOW, updated_at=NOW)
    d.update(kw)
    return d


async def _svc():
    e = make_engine("sqlite+aiosqlite:///:memory:")
    svc = RfqService(e, Settings(database_url="sqlite+aiosqlite:///:memory:", sourcing_client="mock"), None, lambda: NOW)
    await svc.create_tables()
    counter = [0]
    event.listen(e.sync_engine, "before_cursor_execute", lambda *a: counter.__setitem__(0, counter[0] + 1))
    return e, svc, counter


def test_sweep_is_set_based_not_per_row():
    async def go():
        e, svc, n = await _svc()
        reqs, offers = [], []
        for i in range(300):  # 300 negotiating requests whose single offer lapsed, 300 past deadline
            reqs.append(_req(i, status="negotiating"))
            offers.append(_offer(i, f"r{i:05d}", valid_until=NOW - timedelta(days=1)))
        for i in range(300, 600):
            reqs.append(_req(i, deadline=NOW - timedelta(days=1)))
            offers.append(_offer(i, f"r{i:05d}"))
        async with e.begin() as c:
            await c.execute(insert(RequestRow.__table__), reqs)
            await c.execute(insert(OfferRow.__table__), offers)
        n[0] = 0
        async with svc._sessions() as s, s.begin():
            await svc._sweep(s, NOW)
        assert n[0] <= 14, n[0]  # was ~2 queries per lapsed request
        async with e.connect() as c:
            st = dict((await c.execute(sa.text("select status, count(*) from requests group by status"))).all())
            os_ = dict((await c.execute(sa.text("select status, count(*) from offers group by status"))).all())
        assert st == {"open": 300, "expired": 300} and os_ == {"expired": 600}

    asyncio.run(go())


def test_list_mine_loads_invites_in_one_query():
    async def go():
        e, svc, n = await _svc()
        async with e.begin() as c:
            await c.execute(insert(RequestRow.__table__), [_req(i) for i in range(20)])
            await c.execute(insert(RequestInviteRow.__table__),
                            [dict(request_id=f"r{i:05d}", supplier_id=f"sup{i}") for i in range(20)])
        svc._dirty, svc._swept_at = False, NOW
        n[0] = 0
        out = await svc.list_requests("owner", scope="mine", status=None, kind=None, p=1, size=20)
        assert n[0] <= 4, n[0]  # count, page, offer counts, invites (was 3 + one per row)
        assert out["items"][0]["invited_supplier_ids"] == ["sup0"]

    asyncio.run(go())


def test_new_indexes_used_after_migration(tmp_path):
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    command.upgrade(cfg, "head")
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    with eng.begin() as c:
        c.execute(sa.text("create table if not exists _x(i int)"))
        # statistics so the planner behaves as on a populated table
        for i in range(400):
            c.execute(sa.text("insert into reviews(id,deal_id,buyer_id,supplier_ref,reviewer_display,rating,status,"
                              "flagged_for_review,created_at,updated_at) values (:i,:d,'b',:s,'x',5,'published',0,"
                              "'2026-10-01','2026-10-01')"), dict(i=f"v{i}", d=f"d{i}", s=f"sup{i % 20}"))
        c.execute(sa.text("analyze"))
        plan = " ".join(str(r) for r in c.execute(sa.text(
            "explain query plan select * from reviews where supplier_ref='sup1' and status='published' "
            "order by created_at desc, id limit 20")))
        assert "ix_reviews_supplier_status_created" in plan, plan
        plan = " ".join(str(r) for r in c.execute(sa.text(
            "explain query plan select min(deadline) from requests where status in ('open','negotiating') "
            "and deadline is not null")))
        assert "ix_requests_status_deadline" in plan, plan
    eng.dispose()
