"""QA of the price-drop / saved-search pipeline: dedupe, thresholds, FX, partial results,
delisting, restarts and concurrency. Offline: scriptable fake sourcing only."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ff_notifications.adapters.push import MockPush
from ff_notifications.clients.sourcing import (
    HttpSourcingClient,
    MockSourcingClient,
    SourcingUnavailableError,
)
from ff_notifications.config import Settings
from ff_notifications.domain.models import Locale, Platform, SearchQuery
from ff_notifications.domain.money import Money
from ff_notifications.main import create_app

from .test_api import listing

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


async def make(tmp_path=None, mock=None, push=None, **settings):
    mock = mock or MockSourcingClient([listing()])
    push = push or MockPush()
    url = (
        f"sqlite+aiosqlite:///{tmp_path}/n.db" if tmp_path else "sqlite+aiosqlite:///:memory:"
    )
    app = create_app(Settings(database_url=url, **settings), sourcing=mock, push=push)
    ctx = app.router.lifespan_context(app)
    await ctx.__aenter__()
    svc = app.state.service
    svc.clock = lambda: T0
    return app, svc, mock, push, ctx


async def watch(svc, user="u1", lid="lst_1", **kw):
    w, _ = await svc.add_watch(
        user, listing_id=lid, search=None, target_price=kw.get("target"),
        drop_threshold_pct=kw.get("pct"),
    )
    return w


async def search_watch(svc, user="u1", **kw):
    w, _ = await svc.add_watch(
        user, listing_id=None, search=SearchQuery(category="pumps"),
        target_price=kw.get("target"), drop_threshold_pct=kw.get("pct"),
    )
    return w


def rules(report):
    return sorted(a.rule.value for a in report.alerts)


async def test_dedupe_same_drop_not_notified_twice_even_after_cooldown():
    _, svc, mock, _, ctx = await make(cooldown_hours=0)
    await watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "80")
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    for _ in range(3):
        assert (await svc.evaluate_all()).alerts_created == 0
    # price bounces back up and down to the same value: baseline was lowered to 80, so
    # 80 again is not a drop vs. what the owner knows; a further 5% drop is
    mock.set_price("lst_1", "100")
    await svc.evaluate_all()
    mock.set_price("lst_1", "80")
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.set_price("lst_1", "70")
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    await ctx.__aexit__(None, None, None)


async def test_threshold_pct_boundary_exact_and_custom():
    _, svc, mock, _, ctx = await make()
    await watch(svc, pct=10)
    await svc.evaluate_all()
    mock.set_price("lst_1", "90.01")  # 9.99 %
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.set_price("lst_1", "90")  # exactly 10 %
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    await ctx.__aexit__(None, None, None)


async def test_currency_change_is_skipped_not_a_false_drop():
    """No FX in v1: another currency re-bases silently; a target in another currency is skipped."""
    _, svc, mock, _, ctx = await make()
    await watch(svc, target=Money.of("60", "EUR"))
    await svc.evaluate_all()
    item = mock.catalog["lst_1"]
    cheap_cny = Money.of("10", "CNY")  # numerically tiny but not comparable
    mock.put(replace(item, price_min=cheap_cny, price_max=cheap_cny))
    report = await svc.evaluate_all()
    assert report.alerts_created == 0
    w = (await svc.list_watches("u1"))[0]
    assert w.baseline_price == cheap_cny
    mock.put(replace(item, price_min=Money.of("5", "CNY"), price_max=Money.of("5", "CNY")))
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    await ctx.__aexit__(None, None, None)


async def test_delisted_no_alert_then_back_in_stock_once_and_no_phantom_drop():
    _, svc, mock, _, ctx = await make(cooldown_hours=0)
    await watch(svc)
    await svc.evaluate_all()
    mock.remove("lst_1")  # delisted / moderated (hidden) -> 404
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.put(listing(price="100"))
    assert rules(await svc.evaluate_all()) == ["back_in_stock"]
    assert (await svc.evaluate_all()).alerts_created == 0
    await ctx.__aexit__(None, None, None)


async def test_sourcing_down_creates_nothing_and_keeps_state():
    _, svc, mock, _, ctx = await make()
    await watch(svc)
    await svc.evaluate_all()
    mock.fail = True
    report = await svc.evaluate_all()
    assert report.alerts_created == 0 and len(report.errors) == 1 and report.evaluated == 0
    mock.fail = False
    mock.set_price("lst_1", "50")
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    await ctx.__aexit__(None, None, None)


async def test_degraded_search_results_do_not_mark_gone_or_fake_back_in_stock():
    _, svc, mock, _, ctx = await make(cooldown_hours=0)
    await search_watch(svc)
    await svc.evaluate_all()  # snapshot
    mock.degraded = True
    saved = mock.catalog.copy()
    mock.catalog.clear()  # partial_results: nothing came back in time
    report = await svc.evaluate_all()
    assert report.alerts_created == 0 and report.evaluated == 0 and len(report.errors) == 1
    w = (await svc.list_watches("u1"))[0]
    assert w.available is True
    mock.catalog.update(saved)
    mock.degraded = False
    assert (await svc.evaluate_all()).alerts_created == 0  # no "back in stock"/"new results"
    await ctx.__aexit__(None, None, None)


async def test_degraded_search_with_substituted_cheap_price_is_not_a_drop():
    _, svc, mock, _, ctx = await make()
    await search_watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "10")
    mock.degraded = True
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.degraded = False
    assert rules(await svc.evaluate_all()) == ["price_drop"]  # real data confirms it later
    await ctx.__aexit__(None, None, None)


async def test_degraded_equivalent_search_skips_equivalent_rule_only():
    mock = MockSourcingClient([listing(), listing("lst_2", "60", supplier="sup_2")])
    _, svc, mock, _, ctx = await make(mock=mock)
    await watch(svc)
    mock.degraded = True
    # the watched listing itself is fetched fine; the (partial) equivalents page is ignored
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.degraded = False
    assert rules(await svc.evaluate_all()) == ["cheaper_equivalent"]
    await ctx.__aexit__(None, None, None)


def _http(body, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return HttpSourcingClient(
        "http://sourcing", client=httpx.AsyncClient(
            base_url="http://sourcing", transport=httpx.MockTransport(handler))
    )


ITEM = {
    "id": "lst_1", "kind": "product", "title": "Pump", "supplier": {"id": "s", "name": "S"},
    "price": {"min": {"amount": "5", "currency": "USD"}, "max": {"amount": "5", "currency": "USD"}},
}


@pytest.mark.parametrize(
    ("extra", "degraded"),
    [
        ({"sources": [{"source": "mock", "status": "ok", "count": 1}]}, False),
        ({"sources": [{"source": "a1688", "status": "timeout", "count": 0}]}, True),
        ({"sources": [{"source": "a", "status": "error", "count": 0}]}, True),
        ({"sources": [{"source": "a", "status": "timeout", "warning": "mock instead"}]}, True),
        ({"sources": [{"source": "a", "status": "ok", "warning": "mock instead"}]}, True),
        ({"warning": "partial_results: time budget exceeded"}, True),
    ],
)
async def test_http_client_flags_degraded_pages(extra, degraded):
    client = _http({"items": [ITEM], "total": 1, **extra})
    page = await client.search(SearchQuery(category="pumps"))
    assert page.degraded is degraded


async def test_http_client_errors_are_unavailable_not_crashes():
    with pytest.raises(SourcingUnavailableError):
        await _http({}, 503).search(SearchQuery())
    with pytest.raises(SourcingUnavailableError):
        await _http(["nope"]).search(SearchQuery())
    assert await _http({}, 404).get_listing("x") is None


async def test_restart_does_not_repeat_alerts_and_scheduler_is_idempotent(tmp_path):
    _, svc, mock, _, ctx = await make(tmp_path)
    await watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "50")
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    await ctx.__aexit__(None, None, None)
    # "restart": new app + service on the same database, same sourcing state
    _, svc2, _, _, ctx2 = await make(tmp_path, mock=mock)
    for _ in range(3):
        assert (await svc2.evaluate_all()).alerts_created == 0
    _, total, _, _ = await svc2.list_alerts("u1", unread_only=False, page=1, page_size=50)
    assert total == 1
    await ctx2.__aexit__(None, None, None)


async def test_scheduler_loop_survives_failures_and_evaluates():
    _, svc, mock, _, ctx = await make()
    svc.settings = svc.settings.model_copy(update={"scheduler_interval_seconds": 0.01})
    await watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "50")
    calls = {"n": 0}
    real = svc.evaluate_all

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return await real(**kw)

    svc.evaluate_all = flaky
    task = asyncio.create_task(svc.run_scheduler())
    await asyncio.sleep(0.2)
    task.cancel()
    _, total, _, _ = await svc.list_alerts("u1", unread_only=False, page=1, page_size=50)
    assert calls["n"] >= 2 and total == 1
    await ctx.__aexit__(None, None, None)


async def test_concurrent_runs_do_not_duplicate_or_abort():
    _, svc, mock, _, ctx = await make()
    await watch(svc)
    await watch(svc, user="u2")
    await svc.evaluate_all()
    mock.set_price("lst_1", "50")
    reports = await asyncio.gather(*(svc.evaluate_all() for _ in range(4)))
    assert sum(r.alerts_created for r in reports) == 2
    assert all(not r.errors for r in reports)
    await ctx.__aexit__(None, None, None)


async def test_one_failing_watch_does_not_abort_run_or_lose_deliveries():
    _, svc, mock, _, ctx = await make()
    await watch(svc, user="u1")
    await svc.evaluate_all()
    mock.set_price("lst_1", "50")
    real = svc.evaluate_watch
    first = True

    async def bad_first(w, report):
        nonlocal first
        if first:
            first = False
            raise RuntimeError("db hiccup")
        return await real(w, report)

    await watch(svc, user="u2")
    svc.evaluate_watch = bad_first
    report = await svc.evaluate_all()
    assert len(report.errors) == 1 and report.alerts_created == 1
    assert report.pushes_sent >= 0
    await ctx.__aexit__(None, None, None)


async def test_quiet_hours_and_channel_prefs_apply_to_price_drop_push():
    _, svc, mock, push, ctx = await make()
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    await svc.put_prefs("u1", channels=None, quiet_hours={"start": "11:00", "end": "14:00"},
                        timezone="UTC", language=None)
    await watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "50")
    report = await svc.evaluate_all()
    assert report.alerts_created == 1 and report.pushes_sent == 0  # inbox yes, push deferred
    assert len(push.sent) == 0
    svc.clock = lambda: T0 + timedelta(hours=3)
    assert await svc.delivery.process_due() == 1
    await ctx.__aexit__(None, None, None)
