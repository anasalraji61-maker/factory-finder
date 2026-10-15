"""QA5: certificate/document spoofing across suppliers, review rings, cancel/reinstate gaming."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from ff_trust.config import ScoringConfig, Settings
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import ReviewSummary, SupplierSignals
from ff_trust.main import create_app
from ff_trust.verification import normalise_number

CFG = ScoringConfig()
TODAY = date(2026, 10, 15)
ADM = {"X-Admin-Token": "adm-secret"}
BASE = dict(years_in_business=5, verified=True, transactions_count=100, rating_avg=4.0, reviews_count=50)


def mk():
    return TestClient(create_app(Settings(admin_token="adm-secret", verification_rate_limit=100)))


def sub(c, sid, number, f="/v1/media/private/abcdef123456.jpg"):
    return c.post(
        "/v1/trust/verification/documents",
        json={"doc_type": "business_license", "issuing_country": "cn", "files": [f], "number": number, "consent": True},
        headers={"X-Supplier-Id": sid},
    )


@pytest.mark.parametrize(
    "variant",
    ["91310000ma1k3xyz9876", "9131-0000 MA1K 3XYZ 9876", "９１３１００００MA1K3XYZ9876", "٩١٣١٠٠٠٠MA1K3XYZ9876", "91310000МА1K3XYZ9876"],
)
def test_same_number_spoofed_by_formatting_or_script_is_normalised(variant):
    base = "91310000MA1K3XYZ9876"
    assert normalise_number(variant) == normalise_number(base), variant


def test_cert_number_on_many_suppliers_is_flagged_for_every_holder():
    c = mk()
    ids = []
    for i, num in enumerate(["91310000MA1K3XYZ9876", "9131 0000-ma1k3xyz9876", "٩١٣١٠٠٠٠MA1K3XYZ9876"]):
        r = sub(c, f"sup_{i}", num, f=f"/v1/media/private/file{i}abcdef.jpg")
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    listing = c.get("/v1/admin/trust/verification/documents", headers=ADM).json()
    items = listing.get("items") or listing.get("documents") or listing
    flagged = {d["id"] for d in items if d.get("duplicate_elsewhere")}
    assert flagged == set(ids)


def test_document_file_replay_across_suppliers_blocked_even_with_other_extension():
    c = mk()
    assert sub(c, "sup_a", "91310000MA1K3XYZ9876", "/v1/media/private/abcdef123456.jpg").status_code == 201
    r = sub(c, "sup_b", "12345678ABCD9999", "/v1/media/private/ABCDEF123456.pdf")
    assert r.status_code == 409 and r.json()["error"]["code"] == "file_in_use"


def test_duplicate_flag_does_not_leak_to_supplier_view():
    c = mk()
    sub(c, "sup_a", "91310000MA1K3XYZ9876", "/v1/media/private/aaaaaa111111.jpg")
    sub(c, "sup_b", "91310000MA1K3XYZ9876", "/v1/media/private/bbbbbb222222.jpg")
    body = c.get("/v1/trust/verification/documents", headers={"X-Supplier-Id": "sup_b"}).text
    assert "duplicate" not in body and "sup_a" not in body and "91310000" not in body


# ---------- review rings ----------
def test_review_ring_many_fivestars_few_deals_earns_less_than_honest():
    ring = ReviewSummary(count=300, average=5.0, histogram={"5": 300}, completed_deals=3)
    honest = ReviewSummary(count=300, average=4.6, histogram={"5": 200, "4": 80, "3": 20}, completed_deals=300)
    s = lambda rs: assess(SupplierSignals(**BASE, review_summary=rs), CFG, TODAY).score  # noqa: E731
    assert s(ring) < s(honest)


def test_same_minute_burst_reviews_dampened():
    from datetime import UTC, datetime

    t = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    burst = ReviewSummary(count=40, average=5.0, histogram={"5": 40}, completed_deals=40, first_review_at=t, last_review_at=t)
    spread = burst.model_copy(update={"last_review_at": datetime(2026, 10, 14, tzinfo=UTC)})
    s = lambda rs: assess(SupplierSignals(**BASE, review_summary=rs), CFG, TODAY).score  # noqa: E731
    assert s(burst) <= s(spread)


def test_headline_average_contradicted_by_histogram_not_trusted():
    fake = ReviewSummary(count=50, average=5.0, histogram={"1": 40, "5": 10}, completed_deals=50)
    real = ReviewSummary(count=50, average=1.8, histogram={"1": 40, "5": 10}, completed_deals=50)
    s = lambda rs: assess(SupplierSignals(**BASE, review_summary=rs), CFG, TODAY).score  # noqa: E731
    assert s(fake) == s(real)


# ---------- cancel / reinstate gaming ----------
def test_cancel_then_reinstate_cannot_beat_never_cancelling():
    s = lambda **k: assess(SupplierSignals(**BASE, **k), CFG, TODAY).score  # noqa: E731
    clean = s(deals_completed=100, deals_cancelled=0)
    assert s(deals_completed=100, deals_cancelled=30) < clean
    # padding with many tiny completed deals after heavy cancels: share still the rule, never above clean
    assert s(deals_completed=1000, deals_cancelled=300) <= clean
    # hiding cancels by reporting None must not outscore an honest clean record
    assert s(deals_completed=100, deals_cancelled=None) <= clean + 0
