# ruff: noqa: E501
"""QA pass 4: push cap races, two delivery workers, quiet-hours/DST boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ff_notifications.delivery import DeliveryPipeline
from ff_notifications.domain.delivery import Prefs, QuietHours
from ff_notifications.domain.models import Locale, Platform
from ff_notifications.persistence.store import Store

from .test_alert_pipeline import make
from .test_qa2_concurrency import ev


async def test_concurrent_ingests_respect_push_cap(tmp_path):
    _, svc, _, _, ctx = await make(tmp_path, push_daily_cap_per_user=3, delivery_backoff_base_seconds=1)
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    await asyncio.gather(*(svc.ingest_tracking_events([ev(key=f"k{i}", sid=f"shp_{i}")]) for i in range(12)))
    dels = await svc.store.list_deliveries("u1", limit=100)
    assert len(dels) <= 3, len(dels)
    _, total, _, _ = await svc.list_alerts("u1", unread_only=False, page=1, page_size=50)
    assert total == 12  # inbox is never capped
    await ctx.__aexit__(None, None, None)


async def test_two_delivery_workers_send_each_delivery_once(tmp_path):
    _, svc, _, push, ctx = await make(tmp_path)
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    class Slow:
        def __init__(self, inner):
            self.inner = inner

        async def send(self, *a, **k):
            await asyncio.sleep(0.02)
            return await self.inner.send(*a, **k)

    slow = Slow(push)
    real = svc.delivery.process_due

    async def noop():
        return 0

    svc.delivery.process_due = noop  # enqueue only
    await svc.ingest_tracking_events([ev(key="a"), ev(key="b", sid="shp_2")])
    svc.delivery.process_due = real
    svc.delivery.push = slow
    # second worker: own lock + own Store on the same database
    store2 = Store(f"sqlite+aiosqlite:///{tmp_path}/n.db")
    other = DeliveryPipeline(store=store2, push=slow, email=None, settings=svc.settings, clock=svc.clock)
    await asyncio.gather(svc.delivery.process_due(), other.process_due())
    n = len(await svc.store.list_deliveries("u1", limit=50))
    assert n >= 1 and len(push.sent) == n, (len(push.sent), n)
    await store2.dispose()
    await ctx.__aexit__(None, None, None)


ZONES = ["America/New_York", "Europe/London", "Australia/Lord_Howe", "Asia/Baghdad", "Europe/Berlin", "America/Sao_Paulo", "Pacific/Apia"]


@pytest.mark.parametrize("tz", ZONES)
def test_quiet_until_is_always_in_the_future_and_outside_quiet_hours_around_dst(tz):
    zi = ZoneInfo(tz)
    qh = QuietHours("22:00", "07:00")
    for qh in (QuietHours("22:00", "07:00"), QuietHours("23:30", "02:30"), QuietHours("00:30", "01:45"), QuietHours("01:00", "03:00")):
        p = Prefs(owner_id="u", quiet_hours=qh, timezone=tz)
        for year_day in range(0, 366, 1):
            base = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=year_day)
            for h in range(0, 24, 1):
                now = base + timedelta(hours=h, minutes=17)
                until = p.quiet_until(now)
                if until is None:
                    continue
                assert until > now, (tz, qh, now, until)
                assert until - now <= timedelta(hours=26), (tz, qh, now, until)
                assert p.quiet_until(until) is None or p.quiet_until(until) > until
                # at the returned instant the user is no longer in quiet hours (except nonexistent-gap rounding)
                assert not qh.active(until.astimezone(zi)), (tz, qh, now, until)
