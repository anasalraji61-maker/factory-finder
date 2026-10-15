"""Supplier analytics: counters, dedupe, rate limit, authorization, retention, bounded memory, erasure."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from ff_sourcing.analytics import Analytics
from ff_sourcing.db import ListingStatRow

from .test_native import A, B, create, make_app

T0 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, t=T0):
        self.t = t
        self.m = 1000.0

    def now(self):
        return self.t

    def mono(self):
        return self.m

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)
        self.m += seconds


@pytest.fixture
async def ac():
    app = make_app(analytics_hash_key="k", analytics_event_rate_per_min=5)
    clk = Clock()
    a: Analytics = app.state.analytics
    a._clock, a._mono = clk.now, clk.mono
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.app, c.clk = app, clk
        yield c


async def published(c, headers=A, **over):
    lid = (await create(c, headers, **over))["id"]
    r = await c.post(f"/v1/my/listings/{lid}/publish", headers=headers)
    assert r.status_code == 200, r.text
    return lid


async def ev(c, lid, t="view", ip="1.1.1.1", user=None):
    h = {"X-Client-Ip": ip}
    if user:
        h["X-User-Id"] = user
    return await c.post(f"/v1/listings/{lid}/events", json={"type": t}, headers=h)


async def stats(c, h=A, **params):
    r = await c.get("/v1/my/analytics", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_event_counts_and_dedupes(ac):
    lid = await published(ac)
    r = await ev(ac, lid)
    assert r.status_code == 202 and r.json() == {"counted": True}
    assert (await ev(ac, lid)).json() == {"counted": False}  # same viewer, inside the window
    assert (await ev(ac, lid, ip="2.2.2.2")).json() == {"counted": True}
    assert (await ev(ac, lid, "contact_click")).json() == {"counted": True}  # other type is independent
    ac.clk.advance(1801)
    assert (await ev(ac, lid)).json() == {"counted": True}  # window elapsed: counts, but not a new unique
    t = (await stats(ac))["totals"]
    assert t["view"] == 3 and t["contact_click"] == 1
    u = (await stats(ac))["unique_viewers"]
    assert u["view"] == 2 and u["contact_click"] == 1


async def test_user_identity_dedupes_across_ips(ac):
    lid = await published(ac)
    assert (await ev(ac, lid, user="u1", ip="3.3.3.3")).json()["counted"] is True
    assert (await ev(ac, lid, user="u1", ip="4.4.4.4")).json()["counted"] is False
    assert (await ev(ac, lid, user="u2", ip="3.3.3.3")).json()["counted"] is True


async def test_uncountable_listings_answer_the_same(ac):
    draft = (await create(ac))["id"]
    for lid in (draft, "nat_zzzzzzzz", "mock_123"):
        r = await ev(ac, lid, ip=f"9.9.9.{len(lid)}")
        assert r.status_code == 202 and r.json() == {"counted": False}
    assert (await ac.post("/v1/listings/x/events", json={"type": "buy"})).status_code == 422
    assert (await ac.post("/v1/listings/bad id/events", json={"type": "view"})).status_code == 422
    assert (await stats(ac))["totals"]["view"] == 0


async def test_rate_limit_per_ip_and_window_resets(ac):
    lid = await published(ac)
    for _ in range(5):
        assert (await ev(ac, lid, ip="5.5.5.5")).status_code == 202
    r = await ev(ac, lid, ip="5.5.5.5")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert (await ev(ac, lid, ip="6.6.6.6")).status_code == 202  # other IP unaffected
    ac.clk.advance(61)
    assert (await ev(ac, lid, ip="5.5.5.5")).status_code == 202


async def test_no_pii_in_storage(ac):
    lid = await published(ac)
    await ev(ac, lid, ip="203.0.113.77", user="user-secret-1")
    a = ac.app.state.analytics
    async with a.sm() as s:
        rows = (await s.execute(select(ListingStatRow))).all()
    dump = repr(rows) + repr(ListingStatRow.__table__.columns.keys())
    assert "203.0.113.77" not in dump and "user-secret-1" not in dump
    assert set(ListingStatRow.__table__.columns.keys()) == {"listing_id", "day", "metric", "count", "uniques"}


async def test_impressions_from_search_native_only(ac):
    lid = await published(ac, title="Zebrafish ceramic planter")
    r = await ac.get("/v1/search", params={"q": "zebrafish"})
    assert r.status_code == 200 and any(i["id"] == lid for i in r.json()["items"])
    await ac.get("/v1/search", params={"q": "zebrafish"})
    await ac.get("/v1/search", params={"q": "pump"})  # mock catalog: no rows for mock ids
    s = await stats(ac)
    assert s["totals"]["impression"] == 2
    async with ac.app.state.analytics.sm() as s2:
        ids = set((await s2.scalars(select(ListingStatRow.listing_id))).all())
    assert ids == {lid}


async def test_report_counted_once_per_reporter(ac):
    lid = await published(ac)
    for _ in range(2):
        r = await ac.post(f"/v1/listings/{lid}/report", json={"reason": "other"}, headers={"X-User-Id": "rep1"})
        assert r.status_code == 202
    await ac.post(f"/v1/listings/{lid}/report", json={"reason": "other"}, headers={"X-User-Id": "rep2"})
    assert (await stats(ac))["totals"]["report"] == 2


async def test_watchlist_hook(ac):
    lid = await published(ac)
    await ac.app.state.analytics.bump(lid, "watchlist_add")
    assert (await stats(ac))["totals"]["watchlist_add"] == 1


async def test_overview_series_change_conversion_and_top_table(ac):
    l1, l2 = await published(ac, title="One"), await published(ac, title="Two")
    a = ac.app.state.analytics
    d = lambda n: T0 - timedelta(days=n)  # noqa: E731
    async with a.sm() as s:
        for lid, day, metric, n in [
            (l1, d(0), "impression", 100), (l1, d(0), "view", 20), (l1, d(0), "contact_click", 5),
            (l1, d(3), "view", 10), (l2, d(3), "view", 40), (l2, d(3), "contact_click", 4),
            (l1, d(8), "view", 15),  # previous period of days=7
            (l1, d(30), "view", 999),  # outside both
        ]:
            s.add(ListingStatRow(listing_id=lid, day=day.date(), metric=metric, count=n, uniques=n // 2))
        await s.commit()
    s = await stats(ac, days=7)
    assert s["period"] == {"days": 7, "from": "2026-10-09", "to": "2026-10-15", "previous_from": "2026-10-02", "previous_to": "2026-10-08"}
    assert s["totals"]["view"] == 70 and s["previous_totals"]["view"] == 15
    assert s["change_pct"]["view"] == 366.7 and s["change_pct"]["contact_click"] is None
    assert s["conversion"]["view_to_contact"] == round(9 / 70, 4)
    assert s["conversion"]["impression_to_view"] == round(70 / 100, 4)
    assert len(s["series"]) == 7 and s["series"][-1]["date"] == "2026-10-15" and s["series"][-1]["view"] == 20
    assert [r["listing_id"] for r in s["listings"]] == [l2, l1]  # by views desc
    assert s["listings"][0]["view_to_contact"] == 0.1
    one = await stats(ac, days=7, listing_id=l1)
    assert one["totals"]["view"] == 30 and one["listings_total"] == 1
    assert (await stats(ac, days=90))["totals"]["view"] == 1084


async def test_authorization_only_own_listings(ac):
    la = await published(ac, A)
    lb = await published(ac, B)
    await ev(ac, la)
    await ev(ac, lb, ip="7.7.7.7")
    await ev(ac, lb, ip="8.8.8.8")
    assert (await stats(ac, A))["totals"]["view"] == 1
    assert (await stats(ac, B))["totals"]["view"] == 2
    r = await ac.get("/v1/my/analytics", params={"listing_id": lb}, headers=A)
    assert r.status_code == 404 and r.json()["error"]["code"] == "listing_not_found"
    assert (await ac.get("/v1/my/analytics", params={"listing_id": "nat_nope"}, headers=A)).status_code == 404
    for h in ({}, {"X-Supplier-Id": "bad"}):
        assert (await ac.get("/v1/my/analytics", headers=h)).status_code == 403
    assert (await ac.get("/v1/my/analytics", params={"days": 14}, headers=A)).status_code == 422


async def test_internal_token_required_for_events_and_analytics():
    app = make_app(internal_token="sekret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/v1/listings/nat_x/events", json={"type": "view"})).status_code == 401
        assert (await c.get("/v1/my/analytics", headers=A)).status_code == 401
        ok = await c.post("/v1/listings/nat_x/events", json={"type": "view"}, headers={"X-Internal-Token": "sekret"})
        assert ok.status_code == 202


async def test_retention_purge(ac):
    lid = await published(ac)
    a = ac.app.state.analytics
    async with a.sm() as s:
        for n in (0, 399, 400, 401, 500):
            s.add(ListingStatRow(listing_id=lid, day=(T0 - timedelta(days=n)).date(), metric="view", count=1, uniques=0))
        await s.commit()
    assert await a.purge() == 2  # days 401 and 500
    async with a.sm() as s:
        assert await s.scalar(select(func.count()).select_from(ListingStatRow)) == 3


async def test_bounded_memory_and_day_rotation(ac):
    lid = await published(ac)
    a: Analytics = ac.app.state.analytics
    a.rate_per_min, a.dedupe_max, a.unique_cap, a.max_sets, a.limiter_max = 10**6, 50, 10, 3, 40
    for i in range(300):
        await a.record_event(lid, "view", f"10.0.{i // 250}.{i % 250}", None, True)
    assert len(a._seen) <= 50 and len(a._limits) <= 40
    assert len(a._sets[(lid, "view")]) == 10  # saturated, not growing
    t = (await stats(ac))["totals"]["view"]
    assert t == 300  # counts stay exact; only the unique estimate saturates
    assert (await stats(ac))["unique_viewers"]["view"] == 10
    for et in ("contact_click", "share", "view"):  # set-table cap
        await a.record_event(lid, et, "9.9.9.9", None, True)
    assert len(a._sets) <= 3
    ac.clk.advance(86400)  # next UTC day wipes all transient state
    await a.record_event(lid, "view", "9.9.9.9", None, True)
    assert len(a._seen) == 1 and list(a._sets) == [(lid, "view")]


async def test_daily_salt_differs_per_day():
    a = Analytics(None, hash_key="k")  # type: ignore[arg-type]
    d1, d2 = T0.date(), (T0 + timedelta(days=1)).date()
    assert a._hash(d1, "ip:1.2.3.4") == a._hash(d1, "ip:1.2.3.4") != a._hash(d2, "ip:1.2.3.4")


async def test_delete_listing_and_account_erase_remove_stats(ac):
    l1, l2, lb = await published(ac, title="Alpha"), await published(ac, title="Bravo"), await published(ac, B)
    for lid in (l1, l2, lb):
        await ev(ac, lid)
    a = ac.app.state.analytics

    async def n():
        async with a.sm() as s:
            return await s.scalar(select(func.count()).select_from(ListingStatRow))

    assert await n() == 3
    assert (await ac.delete(f"/v1/my/listings/{l1}", headers=A)).status_code == 204
    assert await n() == 2
    r = await ac.delete("/v1/internal/users/u1/data", headers=A)
    assert r.status_code == 200 and r.json()["counts"]["analytics_rows_deleted"] == 1
    assert await n() == 1  # B's row stays
