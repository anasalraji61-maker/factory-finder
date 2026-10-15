import asyncio
from datetime import date

import httpx
from fastapi.testclient import TestClient

from ff_trust.clients.reviews import HttpReviewsClient, MockReviewsClient, parse_summary
from ff_trust.config import ScoringConfig, Settings
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import ReviewSummary, SupplierSignals
from ff_trust.main import create_app

CFG = ScoringConfig()
TODAY = date(2026, 10, 14)
BASE = dict(years_in_business=5, verified=True, transactions_count=100, rating_avg=4.0, reviews_count=50)
PAYLOAD = {"supplier_ref": "s", "count": 40, "average": "4.80", "histogram": {"5": 35, "4": 5},
           "sub_ratings": {"quality": "4.90", "communication": None, "shipping": None}, "completed_deals": 30}  # fmt: skip


def run(c):
    return asyncio.run(c)


def a(summary):
    return assess(SupplierSignals(**BASE, review_summary=summary), CFG, TODAY)


def fac(x, key="platform_reviews"):
    return next((f for f in x.factors if f.key == key), None)


def test_bounded_weight_and_evidence_bilingual():
    f = fac(a(parse_summary(PAYLOAD)))
    assert f and 0 < f.impact <= CFG.weights["platform_reviews"]
    assert "4.80/5" in f.explanation and "Verified-purchase reviews" in f.explanation and "raises" in f.explanation
    assert "تقييمات المشترين الموثقة" in f.explanation_ar and "يرفع" in f.explanation_ar
    bad = fac(a(ReviewSummary(count=500, average=1.0)))
    assert -CFG.weights["platform_reviews"] <= bad.impact < 0


def test_small_sample_dampened():
    big, small = fac(a(ReviewSummary(count=40, average=5.0))), fac(a(ReviewSummary(count=2, average=5.0)))
    assert small.impact < big.impact
    assert "dampened" in small.explanation and "dampened" not in big.explanation


def test_absent_or_empty_does_not_change_score_or_gaps():
    base = assess(SupplierSignals(**BASE), CFG, TODAY)
    assert a(None).score == base.score and a(None).data_gaps == base.data_gaps
    assert fac(a(ReviewSummary(count=0, average=None))) is None
    assert not any(g.key == "platform_reviews" for g in base.data_gaps)


def test_average_from_histogram_when_missing():
    f = fac(a(ReviewSummary(count=10, average=None, histogram={"5": 10})))
    assert f and f.impact > 0


def test_parse_summary():
    assert parse_summary({"count": 0, "average": None}) is None
    assert parse_summary("x") is None
    assert parse_summary({"count": "abc"}) is None
    s = parse_summary(PAYLOAD)
    assert s.average == 4.8 and s.sub_ratings["communication"] is None and s.completed_deals == 30


def _http(handler, **kw):
    cl = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rfq")
    return HttpReviewsClient("http://rfq", client=cl, **kw)


def test_http_client_ok_cache_and_fallbacks():
    calls = []

    def ok(req):
        calls.append(req.url.raw_path.decode())
        return httpx.Response(200, json=PAYLOAD)

    c = _http(ok)
    assert run(c.fetch("sup a/b")).count == 40
    run(c.fetch("sup a/b"))
    assert len(calls) == 1 and calls[0] == "/v1/suppliers/sup%20a%2Fb/review-summary"
    assert run(_http(lambda r: httpx.Response(500)).fetch("x")) is None
    assert run(_http(lambda r: httpx.Response(200, text="not json")).fetch("x")) is None

    def boom(req):
        raise httpx.ConnectTimeout("t")

    assert run(_http(boom).fetch("x")) is None


def test_mock_client_deterministic():
    m = MockReviewsClient()
    assert run(m.fetch("sup_a")) == run(m.fetch("sup_a"))
    assert run(m.fetch("sup_noreviews1")) is None


def test_service_integration_and_failure_fallback():
    off = TestClient(create_app(Settings()))
    on = TestClient(create_app(Settings(reviews_source="mock")))
    r_off = off.get("/v1/trust/suppliers/sup_demo_avg").json()
    r_on = on.get("/v1/trust/suppliers/sup_demo_avg").json()
    assert not any(f["key"] == "platform_reviews" for f in r_off["factors"])
    assert any(f["key"] == "platform_reviews" for f in r_on["factors"]) or run(MockReviewsClient().fetch("sup_demo_avg")) is None

    class Broken:
        name = "broken"

        async def fetch(self, ref):
            raise RuntimeError("down")

    c = TestClient(create_app(Settings(), reviews=Broken()))
    assert c.get("/v1/trust/suppliers/sup_demo_avg").json()["score"] == r_off["score"]


def test_review_timestamps_parsed_and_optional():
    s = parse_summary({**PAYLOAD, "first_review_at": "2026-01-02T03:04:05Z", "last_review_at": "2026-10-01T00:00:00+00:00"})
    assert s.first_review_at.year == 2026 and s.last_review_at.month == 10 and s.last_review_at.utcoffset().total_seconds() == 0
    bad = parse_summary({**PAYLOAD, "first_review_at": "nope", "last_review_at": 5})
    assert bad.first_review_at is None and bad.last_review_at is None
    assert parse_summary(PAYLOAD).last_review_at is None
