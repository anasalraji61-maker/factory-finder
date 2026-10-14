from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_trust.adapters.mock import CURATED, signals_from_hash
from ff_trust.config import ScoringConfig, Settings
from ff_trust.domain.models import FactorKind, TrustBand
from ff_trust.domain.scoring import adjusted_rating, assess, cert_status
from ff_trust.domain.signals import CertificationRecord, SupplierSignals
from ff_trust.main import create_app
from ff_trust.store import ReportStore

CFG = ScoringConfig()
TODAY = date(2026, 10, 14)
BASE = dict(years_in_business=5, verified=True, transactions_count=100, rating_avg=4.0, reviews_count=50)


def sc(today=TODAY, **kw):
    return assess(SupplierSignals(**{**BASE, **kw}), CFG, today).score


def impact(a, key):
    return next(f.impact for f in a.factors if f.key == key)


# ---- bounds + monotonicity of each new signal -------------------------------------------------
@pytest.mark.parametrize(
    ("field", "worse", "better"),
    [
        ("business_license_status", "mismatch", "verified"), ("storefront_age_years", 0.1, 10),
        ("repeat_buyer_rate", 0.0, 0.6), ("response_time_hours", 72, 1), ("refund_rate", 0.2, 0.0),
        ("dispute_rate_recent", 0.06, 0.0), ("confirmed_reports", 3, 0),
    ],
)  # fmt: skip
def test_new_signal_monotonic_and_bounded(field, worse, better):
    lo, hi = sc(**{field: worse}), sc(**{field: better})
    assert lo < hi
    assert 0 <= lo <= 100 and 0 <= hi <= 100
    a = assess(SupplierSignals(**{**BASE, field: worse}), CFG, TODAY)
    key = {"dispute_rate_recent": "dispute_rate"}.get(field, field)
    assert abs(impact(a, key)) <= CFG.weights[key]

def test_license_order():
    order = ["mismatch", "expired", "unverified", "pending", "verified"]
    scores = [sc(business_license_status=s) for s in order]
    assert scores == sorted(scores) and scores[0] < scores[-1]


def test_every_impact_within_weight_cap():
    for sid in [f"s{i}" for i in range(40)]:
        a = assess(signals_from_hash(sid), CFG, TODAY)
        for f in a.factors:
            if f.kind == FactorKind.SIGNAL:
                assert abs(f.impact) <= CFG.weights[f.key], f.key


def test_response_time_curve_monotonic():
    xs = [sc(response_time_hours=h) for h in (0.5, 2, 6, 12, 24, 48, 200)]
    assert xs == sorted(xs, reverse=True)


def test_dispute_recency_decay():
    old_bad = sc(dispute_rate=0.05, dispute_rate_recent=0.0)
    recent_bad = sc(dispute_rate=0.05, dispute_rate_recent=0.05)
    assert old_bad > recent_bad
    # recent improvement does not lift a cap earned by the lifetime rate
    a = assess(CURATED["sup_demo_gold"].model_copy(update={"dispute_rate": 0.2, "dispute_rate_recent": 0.0}), CFG, TODAY)
    assert a.score <= 49 and "dispute_rate_cap" in a.caps_applied
    # recent-only data still works
    assert sc(dispute_rate=None, dispute_rate_recent=0.2) < sc(dispute_rate=None, dispute_rate_recent=0.0)


def test_deal_outcomes_shrinkage_and_monotonic():
    assert sc(deals_completed=100, deals_cancelled=0) > sc(deals_completed=100, deals_cancelled=30)
    # 1 completed / 0 cancelled must not look as good as 200 / 0
    assert sc(deals_completed=1, deals_cancelled=0) < sc(deals_completed=200, deals_cancelled=0)
    # 0/0 is unknown, not bad
    a = assess(SupplierSignals(**BASE, deals_completed=0, deals_cancelled=0), CFG, TODAY)
    assert "deal_outcomes" not in {f.key for f in a.factors}


def test_review_shrinkage():
    assert adjusted_rating(5.0, 1, CFG) < adjusted_rating(5.0, 100, CFG) < 5.0
    assert adjusted_rating(5.0, 1, CFG) < 4.2
    few = assess(SupplierSignals(rating_avg=5.0, reviews_count=2), CFG, TODAY)
    many = assess(SupplierSignals(rating_avg=5.0, reviews_count=300), CFG, TODAY)
    assert impact(few, "rating_avg") < impact(many, "rating_avg")
    # a single 5-star review is worth no more than a mediocre well-reviewed shop being clearly worse
    assert sc(rating_avg=4.9, reviews_count=2) <= sc(rating_avg=4.5, reviews_count=400)


# ---- certifications with expiry ---------------------------------------------------------------
def _recs(*pairs):
    return [CertificationRecord(name=n, expires_on=d) for n, d in pairs]


def test_expired_cert_ignored_and_flagged():
    valid = SupplierSignals(**BASE, certification_records=_recs(("ISO 9001", date(2030, 1, 1)), ("CE", None)))
    stale = SupplierSignals(**BASE, certification_records=_recs(("ISO 9001", date(2025, 1, 1)), ("CE", date(2025, 1, 1))))
    av, as_ = assess(valid, CFG, TODAY), assess(stale, CFG, TODAY)
    assert as_.score < av.score
    assert "certification_expired" in as_.flags and "certification_expired" not in av.flags
    assert any(f.key == "certification_expired" and f.explanation_ar for f in as_.factors)


def test_cert_expiring_soon_and_name_normalisation():
    s = SupplierSignals(**BASE, certifications=["ISO9001", "fcc"],
                        certification_records=_recs(("ISO 9001", TODAY + timedelta(days=30)), ("BSCI", date(2031, 1, 1))))  # fmt: skip
    valid, expired, soon = cert_status(s, TODAY)
    assert valid == {"ISO9001", "FCC", "BSCI"} and not expired and soon == {"ISO9001"}
    assert "certification_expiring" in assess(s, CFG, TODAY).flags
    # a dated expired record overrides the bare name in the legacy list
    s2 = SupplierSignals(**BASE, certifications=["ISO9001"], certification_records=_recs(("ISO 9001", date(2020, 1, 1))))
    assert cert_status(s2, TODAY)[0] == set() and cert_status(s2, TODAY)[1] == {"ISO9001"}


def test_more_valid_certs_score_higher():
    one = sc(certification_records=_recs(("CE", None)))
    three = sc(certification_records=_recs(("CE", None), ("FCC", None), ("BSCI", None)))
    assert one < three


# ---- price anomaly ----------------------------------------------------------------------------
def test_price_anomaly_flag():
    assert "price_anomaly" in assess(SupplierSignals(**BASE, price_vs_market_ratio=0.5), CFG, TODAY).flags
    assert "price_anomaly" in assess(SupplierSignals(**BASE, price_vs_market_ratio=3.0), CFG, TODAY).flags
    assert "price_anomaly" not in assess(SupplierSignals(**BASE, price_vs_market_ratio=1.0), CFG, TODAY).flags


# ---- confidence + data gaps -------------------------------------------------------------------
def test_confidence_range_and_monotonic_in_coverage():
    assert assess(SupplierSignals(), CFG, TODAY).confidence == 0
    prev = -1
    kwargs = [dict(verified=True), dict(response_rate=0.9), dict(refund_rate=0.01), dict(business_license_status="verified"),
              dict(repeat_buyer_rate=0.5)]  # fmt: skip
    acc: dict = {}
    for kw in kwargs:
        acc.update(kw)
        c = assess(SupplierSignals(**acc), CFG, TODAY).confidence
        assert 0 <= c <= 100 and c > prev
        prev = c
    for sid in ("sup_demo_gold", "sup_demo_scam", "x1"):
        assert 0 <= assess(CURATED.get(sid) or signals_from_hash(sid), CFG, TODAY).confidence <= 100


def test_confidence_rewards_sample_size():
    thin = assess(SupplierSignals(rating_avg=4.5, reviews_count=2, transactions_count=3), CFG, TODAY)
    deep = assess(SupplierSignals(rating_avg=4.5, reviews_count=300, transactions_count=900), CFG, TODAY)
    assert thin.confidence < deep.confidence


def test_data_gaps_bilingual_and_unknown_not_bad():
    sparse = SupplierSignals(verified=True, years_in_business=5, rating_avg=4, reviews_count=50, transactions_count=100)
    a = assess(sparse, CFG, TODAY)
    keys = [g.key for g in a.data_gaps]
    assert "business_license_status" in keys and "sanctions_hit" in keys and "verified" not in keys
    assert all(g.label and g.label_ar for g in a.data_gaps)
    weights = [CFG.weights.get(k, 0) for k in keys if k != "sanctions_hit"]
    assert weights == sorted(weights, reverse=True)
    # adding a missing-but-neutral/positive data point never lowers score because of "unknown"; missing adds no negative factor
    assert all(f.impact >= -CFG.weights.get(f.key, 100) for f in a.factors)
    assert assess(SupplierSignals(**CURATED["sup_demo_gold"].model_dump()), CFG, TODAY).data_gaps == ()
    assert len(assess(SupplierSignals(), CFG, TODAY).data_gaps) == 21


# ---- hard-fail rules --------------------------------------------------------------------------
@pytest.mark.parametrize("field", ["sanctions_hit", "blocked"])
def test_hard_fail_red_with_explanation(field):
    a = assess(CURATED["sup_demo_gold"].model_copy(update={field: True}), CFG, TODAY)
    assert a.band == TrustBand.RED and a.score <= 20
    key = "sanctions_hit" if field == "sanctions_hit" else "blocked_flag"
    assert key in a.caps_applied and key in a.flags
    cap = next(f for f in a.factors if f.key == key)
    assert cap.kind == FactorKind.CAP and cap.explanation and cap.explanation_ar
    # even with almost no data
    assert assess(SupplierSignals(**{field: True}), CFG, TODAY).band == TrustBand.RED


def test_score_invariant_still_holds_v2():
    for sid in ["sup_cn_001", "sup_demo_avg", "sup_demo_scam", "sup_demo_gold", "sup_demo_sanctioned"]:
        a = assess(CURATED.get(sid) or signals_from_hash(sid), CFG, TODAY)
        sig = sum(f.impact for f in a.factors if f.kind == FactorKind.SIGNAL)
        cap = sum(f.impact for f in a.factors if f.kind == FactorKind.CAP)
        assert a.score == max(0, min(100, a.baseline + sig)) + cap
        assert all(f.explanation and f.explanation_ar for f in a.factors)


def test_mock_fixtures_deterministic_and_have_v2_fields():
    s = signals_from_hash("sup_cn_007")
    assert s == signals_from_hash("sup_cn_007")
    for sig in (s, *CURATED.values()):
        assert sig.business_license_status and sig.certification_records is not None and sig.deals_completed is not None
    assert {assess(signals_from_hash(f"sup_cn_{i:03d}"), CFG, TODAY).band for i in range(80)} >= {TrustBand.GREEN, TrustBand.RED}


# ---- API: v2 fields, history, reports ---------------------------------------------------------
@pytest.fixture
def client():
    return TestClient(create_app(Settings()))


def test_api_v2_fields(client):
    b = client.get("/v1/trust/suppliers/sup_demo_gold").json()
    assert 0 <= b["confidence"] <= 100 and isinstance(b["confidence"], int) and b["model_version"] == "trust-v2"
    assert b["data_gaps"] == [] and "flags" in b
    e = client.post("/v1/trust/evaluate", json={"verified": True}).json()
    assert e["band"] == "unknown" and e["data_gaps"] and {"key", "label", "label_ar"} <= set(e["data_gaps"][0])
    r = client.post("/v1/trust/evaluate", json={"blocked": True}).json()
    assert r["band"] == "red" and r["score"] <= 20
    assert client.post("/v1/trust/evaluate", json={"business_license_status": "bogus"}).status_code == 422


def test_history_ordering_and_determinism(client):
    h1 = client.get("/v1/trust/suppliers/sup_demo_avg/history")
    assert h1.status_code == 200
    pts = h1.json()["points"]
    assert len(pts) >= 12
    ats = [p["at"] for p in pts]
    assert ats == sorted(ats)
    assert all(0 <= p["score"] <= 100 and p["band"] in {"green", "yellow", "red", "unknown"} for p in pts)
    assert pts[-1]["source"] == "snapshot" and pts[0]["source"] == "mock"
    mock1 = [(p["score"], p["band"]) for p in pts if p["source"] == "mock"]
    mock2 = [(p["score"], p["band"]) for p in client.get("/v1/trust/suppliers/sup_demo_avg/history").json()["points"] if p["source"] == "mock"]
    assert mock1 == mock2
    assert client.get("/v1/trust/suppliers/sup_demo_sanctioned/history").json()["points"][0]["band"] == "red"


def test_history_unknown_and_disabled():
    c = TestClient(create_app(Settings(adapter="alibaba")))
    assert c.get("/v1/trust/suppliers/x/history").status_code == 503


H = {"X-User-Id": "u1"}


def test_report_ok_and_no_score_effect(client):
    before = client.get("/v1/trust/suppliers/sup_demo_gold").json()
    r = client.post("/v1/trust/suppliers/sup_demo_gold/report", json={"type": "fraud", "text": "  never shipped  "}, headers=H)
    assert r.status_code == 201
    b = r.json()
    assert b["status"] == "pending_review" and b["text"] == "never shipped" and b["score_effect"] == "none_until_reviewed"
    after = client.get("/v1/trust/suppliers/sup_demo_gold").json()
    assert after["score"] == before["score"] and after["factors"] == before["factors"]


@pytest.mark.parametrize(
    "body", [{"type": "nope", "text": "x"}, {"type": "fraud", "text": ""}, {"type": "fraud", "text": "   "},
             {"type": "fraud", "text": "a" * 1001}, {"type": "fraud"}, {"type": "fraud", "text": "x", "extra": 1}],
)  # fmt: skip
def test_report_validation(client, body):
    r = client.post("/v1/trust/suppliers/sup_demo_gold/report", json=body, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_report_max_length_accepted_and_needs_user(client):
    assert client.post("/v1/trust/suppliers/s/report", json={"type": "other", "text": "a" * 1000}, headers=H).status_code == 201
    r = client.post("/v1/trust/suppliers/s/report", json={"type": "other", "text": "x"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "user_required"


def test_report_rate_limit_per_user():
    c = TestClient(create_app(Settings(report_rate_limit=2)))
    post = lambda uid: c.post("/v1/trust/suppliers/s/report", json={"type": "other", "text": "x"}, headers={"X-User-Id": uid})  # noqa: E731
    assert [post("a").status_code for _ in range(2)] == [201, 201]
    r = post("a")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert post("b").status_code == 201  # other users unaffected


async def test_report_rate_limit_window_expires():
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    rs = ReportStore(limit=1, window_seconds=60, clock=lambda: now[0])
    await rs.add("s", "u", "fraud", "x")
    from ff_trust.store import RateLimited

    with pytest.raises(RateLimited):
        await rs.add("s", "u", "fraud", "y")
    now[0] += timedelta(seconds=61)
    await rs.add("s", "u", "fraud", "z")


async def test_report_affects_score_only_after_accept():
    app = create_app(Settings())
    c = TestClient(app)
    svc = app.state.service
    base = c.get("/v1/trust/suppliers/sup_demo_avg").json()["score"]
    rid = c.post("/v1/trust/suppliers/sup_demo_avg/report", json={"type": "fraud", "text": "x"}, headers=H).json()["id"]
    assert c.get("/v1/trust/suppliers/sup_demo_avg").json()["score"] == base
    await svc.review_report(rid, "rejected")
    assert c.get("/v1/trust/suppliers/sup_demo_avg").json()["score"] == base
    await svc.review_report(rid, "accepted")
    assert c.get("/v1/trust/suppliers/sup_demo_avg").json()["score"] < base
