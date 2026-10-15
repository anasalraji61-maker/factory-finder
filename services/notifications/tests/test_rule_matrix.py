"""Rule matrix for alert evaluation: thresholds, targets, currencies, availability, saved
searches, quiet hours, digests, dedupe, daily caps, channel fallback, opt-out, degraded search.
Offline: pure domain functions plus the service against scriptable mocks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from ff_notifications.adapters.email import MockEmail
from ff_notifications.adapters.push import MockPush
from ff_notifications.clients.sourcing import (
    HttpSourcingClient,
    MockSourcingClient,
    SourcingUnavailableError,
)
from ff_notifications.config import Settings
from ff_notifications.domain.delivery import DeliveryStatus, Prefs, QuietHours
from ff_notifications.domain.models import Locale, Platform, SearchQuery, TrustBand
from ff_notifications.domain.money import Money, dropped_at_least
from ff_notifications.domain.rules import target_check
from ff_notifications.main import create_app

from .test_alert_pipeline import T0, make, rules, search_watch, watch
from .test_api import listing

D = Decimal


# --------------------------------------------------------------- price drop % exactness


@pytest.mark.parametrize(
    ("old", "new", "pct", "expected"),
    [
        ("100", "95", "5", True),
        ("100", "95.01", "5", False),
        ("100", "100", "5", False),
        ("100", "105", "5", False),
        ("0.30", "0.27", "10", True),  # binary floats get this wrong
        ("19.99", "17.991", "10", True),  # exactly 10 %
        ("19.99", "17.992", "10", False),
        ("1234567890.12", "1111111101.108", "10", True),
        ("0", "0", "5", False),  # zero baseline never divides
        ("100", "0", "100", True),
        ("100", "99.9999999", "0.00001", False),
        ("100", "99.99999", "0.00001", True),
    ],
)
def test_dropped_at_least_is_exact(old, new, pct, expected):
    assert dropped_at_least(D(old), D(new), D(pct)) is expected


async def test_threshold_zero_is_rejected_so_flat_price_never_alerts():
    _, svc, _, _, ctx = await make()
    from ff_notifications.errors import Invalid

    with pytest.raises(Invalid):
        await svc.add_watch(
            "u1", listing_id="lst_1", search=None, target_price=None, drop_threshold_pct=D(0)
        )
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- target price


@pytest.mark.parametrize(
    ("target", "price", "reached", "expected"),
    [
        ("80", "80", False, (True, False)),  # equal counts
        ("80", "79.99", False, (True, False)),
        ("80", "80.01", False, (False, False)),
        ("80", "70", True, (False, True)),  # already told
        ("80", "90", True, (False, False)),  # re-arms above the target
        (None, "70", False, (False, False)),
    ],
)
def test_target_check_matrix(target, price, reached, expected):
    t = Money.of(target, "USD") if target else None
    assert target_check(t, Money.of(price, "USD"), reached) == expected


def test_target_in_other_currency_never_fires():
    assert target_check(Money.of("80", "EUR"), Money.of("1", "USD"), False) == (False, False)


async def test_below_target_wins_over_price_drop_once_then_rearms():
    _, svc, mock, _, ctx = await make(cooldown_hours=0)
    await watch(svc, target=Money.of("80", "USD"))
    await svc.evaluate_all()
    mock.set_price("lst_1", "80")
    assert rules(await svc.evaluate_all()) == ["below_target"]
    mock.set_price("lst_1", "79")
    assert (await svc.evaluate_all()).alerts_created == 0  # 1.25 % < 5 %, already told
    mock.set_price("lst_1", "95")
    await svc.evaluate_all()
    mock.set_price("lst_1", "75")
    assert rules(await svc.evaluate_all()) == ["below_target"]
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- MOQ / availability


async def test_moq_change_alone_never_alerts_and_moq_filter_reaches_sourcing():
    _, svc, mock, _, ctx = await make()
    await watch(svc)
    await svc.evaluate_all()
    mock.put(replace(mock.catalog["lst_1"], moq=1))
    mock.put(replace(mock.catalog["lst_1"], moq=5000))
    assert (await svc.evaluate_all()).alerts_created == 0
    assert SearchQuery(category="pumps", moq_max=100).to_params()["moq_max"] == "100"
    await ctx.__aexit__(None, None, None)


async def test_back_in_stock_needs_a_prior_sighting_and_fires_once():
    _, svc, mock, _, ctx = await make(cooldown_hours=0)
    mock.remove("lst_1")
    await watch(svc)
    assert (await svc.evaluate_all()).alerts_created == 0  # never seen: nothing to restock
    mock.put(listing(price="100"))
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.remove("lst_1")
    await svc.evaluate_all()
    mock.put(listing(price="100"))
    assert rules(await svc.evaluate_all()) == ["back_in_stock"]
    assert (await svc.evaluate_all()).alerts_created == 0
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- saved searches


async def test_new_supplier_match_alerts_once_and_ignores_red_trust():
    mock = MockSourcingClient([listing("lst_1", "100", supplier="s1")])
    _, svc, mock, _, ctx = await make(mock=mock, cooldown_hours=0)
    await search_watch(svc)
    await svc.evaluate_all()  # snapshot, silent
    mock.put(listing("lst_2", "100", supplier="s2", trust=TrustBand.RED))
    assert (await svc.evaluate_all()).alerts_created == 0
    mock.put(listing("lst_3", "100", supplier="s3"))
    assert rules(await svc.evaluate_all()) == ["new_results"]
    assert (await svc.evaluate_all()).alerts_created == 0
    await ctx.__aexit__(None, None, None)


async def test_saved_search_in_other_currency_does_not_fake_a_drop():
    mock = MockSourcingClient([listing("lst_1", "100")])
    _, svc, mock, _, ctx = await make(mock=mock, cooldown_hours=0)
    await search_watch(svc)
    await svc.evaluate_all()
    cny = Money.of("1", "CNY")
    mock.catalog.clear()
    mock.put(replace(listing("lst_9", "1"), price_min=cny, price_max=cny))
    assert "price_drop" not in rules(await svc.evaluate_all())
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- quiet hours / timezones


@pytest.mark.parametrize(
    ("start", "end", "hhmm", "active"),
    [
        ("22:00", "07:00", "22:00", True),
        ("22:00", "07:00", "06:59", True),
        ("22:00", "07:00", "07:00", False),  # end exclusive
        ("22:00", "07:00", "21:59", False),
        ("22:00", "07:00", "00:00", True),
        ("11:00", "14:00", "13:59", True),
        ("11:00", "14:00", "14:00", False),
        ("10:00", "10:00", "10:00", False),  # empty window
    ],
)
def test_quiet_window_boundaries(start, end, hhmm, active):
    h, m = map(int, hhmm.split(":"))
    assert QuietHours(start, end).active(datetime(2026, 10, 13, h, m, tzinfo=UTC)) is active


@pytest.mark.parametrize(
    ("tz", "now_utc", "quiet"),
    [
        ("Asia/Baghdad", datetime(2026, 10, 13, 20, 0, tzinfo=UTC), True),  # 23:00 local
        ("UTC", datetime(2026, 10, 13, 20, 0, tzinfo=UTC), False),
        ("America/New_York", datetime(2026, 10, 13, 4, 0, tzinfo=UTC), True),  # 00:00 EDT
        ("America/New_York", datetime(2026, 10, 13, 12, 0, tzinfo=UTC), False),  # 08:00 EDT
        ("Asia/Tokyo", datetime(2026, 10, 13, 14, 0, tzinfo=UTC), True),  # 23:00 local
    ],
)
def test_quiet_hours_use_user_timezone(tz, now_utc, quiet):
    prefs = Prefs(owner_id="u", quiet_hours=QuietHours("22:00", "07:00"), timezone=tz)
    assert (prefs.in_quiet_hours(now_utc) is not None) is quiet


def test_quiet_until_is_the_next_window_end_in_utc():
    prefs = Prefs(owner_id="u", quiet_hours=QuietHours("22:00", "07:00"), timezone="Asia/Baghdad")
    now = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)  # 23:00 Baghdad
    assert prefs.quiet_until(now) == datetime(2026, 10, 14, 4, 0, tzinfo=UTC)
    assert prefs.quiet_until(datetime(2026, 10, 13, 12, 0, tzinfo=UTC)) is None


# --------------------------------------------------------------- dedupe windows / cooldown


async def test_cooldown_holds_a_new_drop_then_releases_it_after_the_window():
    _, svc, mock, _, ctx = await make(cooldown_hours=24)
    await watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "80")
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    mock.set_price("lst_1", "60")  # a further 25 % drop inside the window
    report = await svc.evaluate_all()
    assert report.alerts_created == 0
    assert {
        "watch_id": report.skipped[0]["watch_id"],
        "rule": "price_drop",
        "reason": "cooldown",
    } in report.skipped
    svc.clock = lambda: T0 + timedelta(hours=24, minutes=1)
    assert rules(await svc.evaluate_all()) == ["price_drop"]
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- delivery matrix


async def delivery_env(**settings):
    mock = MockSourcingClient([listing()])
    push, email = MockPush(), MockEmail()
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", **settings),
        sourcing=mock,
        push=push,
        email=email,
    )
    ctx = app.router.lifespan_context(app)
    await ctx.__aenter__()
    svc = app.state.service
    svc.clock = lambda: T0
    return svc, mock, push, email, ctx


async def drop(svc, mock, price):
    mock.set_price("lst_1", price)
    return await svc.evaluate_all()


async def test_no_device_falls_back_to_inbox_only():
    svc, mock, push, _, ctx = await delivery_env()
    await watch(svc)
    await svc.evaluate_all()
    report = await drop(svc, mock, "50")
    assert report.alerts_created == 1 and report.pushes_sent == 0 and push.sent == []
    items, total, _ = await svc.store.list_alerts("u1", unread_only=False, offset=0, limit=10)
    assert total == 1 and items[0].rule.value == "price_drop"
    await ctx.__aexit__(None, None, None)


async def test_push_provider_off_or_channel_dropped_keeps_inbox():
    svc, mock, push, _, ctx = await delivery_env()
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    await svc.put_prefs(
        "u1", channels={"price_drop": ["in_app"]}, quiet_hours=None, timezone=None, language=None
    )
    await watch(svc)
    await svc.evaluate_all()
    report = await drop(svc, mock, "50")
    assert report.alerts_created == 1 and push.sent == []
    await ctx.__aexit__(None, None, None)


async def test_opt_out_between_enqueue_and_send_is_honoured_immediately():
    svc, mock, push, _, ctx = await delivery_env()
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    await svc.put_prefs(
        "u1",
        channels=None,
        quiet_hours={"start": "11:00", "end": "14:00"},
        timezone="UTC",
        language=None,
    )
    await watch(svc)
    await svc.evaluate_all()
    await drop(svc, mock, "50")  # push deferred by quiet hours
    await svc.put_prefs(
        "u1", channels={"price_drop": ["in_app"]}, quiet_hours=None, timezone=None, language=None
    )
    svc.clock = lambda: T0 + timedelta(hours=3)
    assert await svc.delivery.process_due() == 0
    assert push.sent == []
    rows = await svc.store.list_deliveries("u1")
    assert [r.status for r in rows] == [DeliveryStatus.SKIPPED]
    await ctx.__aexit__(None, None, None)


async def test_daily_push_cap_limits_pushes_not_inbox_and_resets_after_24h():
    svc, mock, push, _, ctx = await delivery_env(cooldown_hours=0, push_daily_cap_per_user=2)
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    await watch(svc, pct=1)
    await svc.evaluate_all()
    for price in ("90", "80", "70", "60"):
        await drop(svc, mock, price)
    assert len(push.sent) == 2
    _, total, _ = await svc.store.list_alerts("u1", unread_only=False, offset=0, limit=10)
    assert total == 4
    svc.clock = lambda: T0 + timedelta(hours=25)
    await drop(svc, mock, "50")
    assert len(push.sent) == 3
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- digest batching / opt-out


async def seed_digest_user(svc, tz="UTC", channels=None):
    await svc.store.put_prefs(
        Prefs(
            owner_id="u1",
            timezone=tz,
            digest_email="b@example.com",
            explicit=True,
            channels={"price_drop": ("in_app", "email"), **(channels or {})},
        )
    )


async def test_digest_batches_one_mail_per_local_day_and_waits_for_08_local():
    svc, mock, _, email, ctx = await delivery_env(cooldown_hours=0)
    await seed_digest_user(svc, tz="Asia/Tokyo")  # T0 12:00 UTC = 21:00 JST
    await watch(svc)
    await svc.evaluate_all()
    await drop(svc, mock, "80")
    await drop(svc, mock, "60")
    svc.clock = lambda: datetime(2026, 10, 13, 22, 0, tzinfo=UTC)  # 07:00 JST next day
    assert await svc.send_digests() == 0
    svc.clock = lambda: datetime(2026, 10, 13, 23, 30, tzinfo=UTC)  # 08:30 JST
    assert await svc.send_digests() == 1
    assert len(email.sent) == 1 and email.sent[0]["body"].count("- ") == 2  # batched
    assert await svc.send_digests() == 0  # same local day
    await ctx.__aexit__(None, None, None)


async def test_digest_opt_out_is_honoured_immediately():
    svc, mock, _, email, ctx = await delivery_env()
    await seed_digest_user(svc)
    await watch(svc)
    await svc.evaluate_all()
    await drop(svc, mock, "50")
    await svc.put_prefs(
        "u1", channels={"price_drop": ["in_app"]}, quiet_hours=None, timezone=None, language=None
    )
    assert await svc.send_digests() == 0
    assert email.sent == []
    await ctx.__aexit__(None, None, None)


# --------------------------------------------------------------- degraded search handling


def _http(body, status=200):
    return HttpSourcingClient(
        "http://s",
        client=httpx.AsyncClient(
            base_url="http://s",
            transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)),
        ),
    )


@pytest.mark.parametrize("body", [{}, {"items": None}, {"total": 0}, {"items": "x"}])
async def test_http_200_without_item_list_is_a_failure_not_empty(body):
    with pytest.raises(SourcingUnavailableError):
        await _http(body).search(SearchQuery(category="pumps"))


async def test_inconsistent_empty_page_with_positive_total_is_degraded():
    page = await _http({"items": [], "total": 7}).search(SearchQuery())
    assert page.degraded is True
    assert (await _http({"items": [], "total": 0}).search(SearchQuery())).degraded is False


@pytest.mark.parametrize("mode", ["fail", "degraded"])
async def test_failed_or_degraded_empty_search_never_alerts_or_changes_state(mode):
    mock = MockSourcingClient([listing("lst_1", "100")])
    _, svc, mock, _, ctx = await make(mock=mock, cooldown_hours=0)
    await search_watch(svc)
    await svc.evaluate_all()
    before = (await svc.list_watches("u1"))[0]
    saved = dict(mock.catalog)
    mock.catalog.clear()
    setattr(mock, mode, True)
    report = await svc.evaluate_all()
    assert report.alerts_created == 0 and report.errors
    setattr(mock, mode, False)
    mock.catalog.update(saved)
    assert (await svc.evaluate_all()).alerts_created == 0  # no phantom back_in_stock
    after = (await svc.list_watches("u1"))[0]
    assert after.available is True and before.baseline_price == after.baseline_price
    await ctx.__aexit__(None, None, None)
