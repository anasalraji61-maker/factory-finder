"""Bilingual coverage: every server-produced user-facing string exists in ar + en."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ff_notifications import i18n
from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.delivery import digest_text
from ff_notifications.domain import messages as M
from ff_notifications.domain import tracking
from ff_notifications.domain.delivery import DEFAULT_TIMEZONE, Prefs, QuietHours
from ff_notifications.domain.models import (
    Alert,
    AlertMessage,
    AlertPayload,
    Locale,
    RuleKind,
    SearchQuery,
)
from ff_notifications.domain.money import Money
from ff_notifications.main import create_app
from ff_notifications.service import verification_text

from .test_api import listing

ARABIC = re.compile(r"[؀-ۿ]")
ARABIC_INDIC = re.compile(r"[٠-٩۰-۹]")
SRC = Path(__file__).resolve().parents[1] / "src" / "ff_notifications"


def _all_messages() -> list[tuple[str, AlertMessage]]:
    a, b = listing("lst_1", "100"), listing("lst_2", "80", supplier="sup_2")
    old, new, tgt = Money.of("100", "USD"), Money.of("1234.5", "USD"), Money.of("90", "EUR")
    out: list[tuple[str, AlertMessage]] = []
    for q in (
        SearchQuery(q="pump"),
        SearchQuery(category="pumps"),
        SearchQuery(kind="raw_material"),
        SearchQuery(),
    ):
        tag = repr(q)
        out += [
            (f"drop_search {tag}", M.price_drop_search(q, a, old, new, Decimal("12.5"), tgt)),
            (f"drop_search_nt {tag}", M.price_drop_search(q, a, old, new, Decimal("12.5"))),
            (f"target_search {tag}", M.below_target_search(q, a, new, tgt)),
            (f"stock_search {tag}", M.back_in_stock_search(q, 3, new)),
            (f"stock_search0 {tag}", M.back_in_stock_search(q, 1, None)),
            (f"new_cheapest {tag}", M.new_results(q, 4, a, True)),
            (f"new_other {tag}", M.new_results(q, 1, a, False)),
        ]
    out += [
        ("drop_listing", M.price_drop_listing(a, old, new, Decimal("20"), tgt)),
        ("target_listing", M.below_target_listing(a, new, tgt)),
        ("stock_listing", M.back_in_stock_listing(a)),
        ("cheaper", M.cheaper_equivalent(a, b, Decimal("20"))),
    ]
    out += [(f"push_summary {n}", M.push_summary(n)) for n in (1, 2, 3, 10, 11, 120)]
    for status in [*tracking.STATUS_TEXT, None]:
        for rule, payload in (
            (RuleKind.SHIPMENT_STATUS, {"status": status, "eta": "2026-11-01"}),
            (RuleKind.SHIPMENT_DELAYED, {"status": status, "delay_hours": 30.4}),
            (RuleKind.SHIPMENT_DELAYED, {}),
        ):
            ev = tracking.TrackingEvent("k", "u1", "s1", "status_changed", payload)
            if rule is RuleKind.SHIPMENT_DELAYED:
                ev = tracking.TrackingEvent("k", "u1", "s1", "shipment_delayed", payload)
            msg, _ = tracking.build(ev)
            out.append((f"tracking {status} {rule}", msg))
    return out


@pytest.mark.parametrize(("tag", "msg"), _all_messages())
def test_alert_message_both_languages(tag, msg):
    for field in (msg.title, msg.title_ar, msg.body, msg.body_ar):
        assert field and field.strip(), tag
    assert ARABIC.search(msg.title_ar), (tag, msg.title_ar)
    assert ARABIC.search(msg.body_ar), (tag, msg.body_ar)
    assert not ARABIC.search(msg.title + msg.body), (tag, "English text contains Arabic")
    assert not ARABIC_INDIC.search(msg.title_ar + msg.body_ar), (tag, "Arabic-Indic digits")


def test_status_table_complete():
    for key, (en, ar) in tracking.STATUS_TEXT.items():
        assert en.strip() and ARABIC.search(ar), key
    assert tracking.status_texts(None)[1] and ARABIC.search(tracking.status_texts(None)[1])


def test_tracking_nameless_shipment_has_no_english_filler_in_arabic():
    ev = tracking.TrackingEvent("k", "u1", "s1", "status_changed", {"status": "delivered"})
    msg, _ = tracking.build(ev)
    assert not re.search(r"[A-Za-z]", msg.body_ar), msg.body_ar


def test_amounts_use_western_digits_with_currency_code():
    msg = M.price_drop_listing(
        listing(), Money.of("100", "USD"), Money.of("1234.5", "USD"), Decimal("12.5")
    )
    assert "1,234.50 USD" in msg.body_ar and "100.00 USD" in msg.body_ar
    assert "1,234.50 USD" in msg.body
    assert "12.5٪" in msg.body_ar  # Western digits + Arabic percent sign
    assert not ARABIC_INDIC.search(msg.body_ar)


def test_digest_and_verification_texts_bilingual():
    msg = M.push_summary(2)
    al = Alert(
        "a1", "u1", "w1", RuleKind.PRICE_DROP, msg, AlertPayload(listing_ids=()), "f",
        datetime(2026, 10, 1, tzinfo=UTC),
    )  # fmt: skip
    for lang, pat in ((Locale.AR, ARABIC), (Locale.EN, re.compile(r"digest"))):
        subject, body = digest_text([al], lang)
        assert pat.search(subject) and body.strip()
    subject, body = verification_text("123456")
    assert ARABIC.search(subject) and ARABIC.search(body) and re.search(r"[A-Za-z]{4}", body)
    assert "123456" in body and not ARABIC_INDIC.search(body)


# ---------------------------------------------------------------- error message tables


def _error_codes() -> set[str]:
    codes: set[str] = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        codes |= set(re.findall(r"code=\"([a-z_]+)\"", text))
        codes |= set(re.findall(r"^\s+code = \"([a-z_]+)\"", text, re.M))
        codes |= set(re.findall(r"status, code = \d+, \"([a-z_]+)\"", text))
    codes |= {"validation_error", "not_found", "http_error"}
    return codes


@pytest.mark.parametrize("code", sorted(_error_codes()))
def test_every_error_code_has_arabic(code):
    ar = i18n.ERRORS_AR.get(code)
    assert ar and ARABIC.search(ar), code
    assert not ARABIC_INDIC.search(ar)


def test_error_envelope_carries_message_ar():
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", use_mock_sourcing=True),
        sourcing=MockSourcingClient(),
    )
    with TestClient(app) as c:
        r = c.get("/v1/watchlist/nope", headers={"X-User-Id": "u1"})
        r2 = c.get("/v1/alerts")  # no user header
        r3 = c.post("/v1/watchlist", headers={"X-User-Id": "u1"}, json={})
    for resp in (r, r2, r3):
        err = resp.json()["error"]
        assert err["message"] and ARABIC.search(err["message_ar"]), resp.text


# ---------------------------------------------------------------- timezone fallback


def test_quiet_hours_use_recipient_timezone():
    now = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)  # 23:00 Baghdad, 22:00 Istanbul?? (+3 both)
    qh = QuietHours("22:00", "07:00")
    assert Prefs("u", quiet_hours=qh, timezone="Asia/Baghdad").in_quiet_hours(now)
    # 20:00 UTC = 16:00 New York (EDT): not quiet
    assert Prefs("u", quiet_hours=qh, timezone="America/New_York").in_quiet_hours(now) is None
    until = Prefs("u", quiet_hours=qh, timezone="Asia/Baghdad").quiet_until(now)
    assert until == datetime(2026, 10, 14, 4, 0, tzinfo=UTC)  # 07:00 Baghdad


@pytest.mark.parametrize("bad", ["", "Not/AZone", "../etc/passwd", "UTC\x00"])
def test_invalid_or_empty_timezone_falls_back_to_baghdad(bad):
    now = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)  # 23:00 Baghdad
    qh = QuietHours("22:00", "07:00")
    p = Prefs("u", quiet_hours=qh, timezone=bad)
    assert p.in_quiet_hours(now) is qh
    assert p.quiet_until(now) == datetime(2026, 10, 14, 4, 0, tzinfo=UTC)
    assert DEFAULT_TIMEZONE == "Asia/Baghdad"
