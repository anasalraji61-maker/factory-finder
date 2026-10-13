import pytest

from ff_trust.adapters.mock import CURATED, MockSignalsAdapter, signals_from_hash
from ff_trust.config import ScoringConfig
from ff_trust.domain.models import TrustBand
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import SupplierSignals

CFG = ScoringConfig()
BASE = dict(years_in_business=5, verified=True, transactions_count=100, rating_avg=4.0, reviews_count=50)


def score(**kw):
    return assess(SupplierSignals(**{**BASE, **kw}), CFG).score


@pytest.mark.parametrize(
    ("field", "low", "high"),
    [
        ("years_in_business", 1, 12), ("transactions_count", 5, 1000), ("response_rate", 0.3, 0.95),
        ("rating_avg", 3.0, 4.8), ("reviews_count", 5, 400), ("dispute_rate", 0.07, 0.0),
        ("domain_age_years", 0.5, 10), ("contact_consistency", 0.2, 0.9), ("country_risk", 0.9, 0.1),
        ("certifications", [], ["ISO9001", "CE"]), ("third_party_audit", False, True),
        ("verified", False, True), ("has_physical_address", False, True),
    ],
)  # fmt: skip
def test_monotonic(field, low, high):
    assert score(**{field: low}) <= score(**{field: high})
    assert score(**{field: low}) < score(**{field: high}) or field in {"reviews_count"}


def test_diminishing_returns():
    gain_early = score(years_in_business=5) - score(years_in_business=1)
    gain_late = score(years_in_business=30) - score(years_in_business=26)
    assert gain_early >= gain_late


def test_price_too_cheap_is_penalised_and_capped():
    ok = assess(SupplierSignals(**BASE, price_vs_market_ratio=1.0), CFG)
    cheap = assess(SupplierSignals(**BASE, price_vs_market_ratio=0.2), CFG)
    assert cheap.score < ok.score
    assert assess(SupplierSignals(**{k: v for k, v in CURATED["sup_demo_gold"] if k != "supplier_id"} | {"price_vs_market_ratio": 0.2}), CFG).score <= 59


def test_thresholds():
    cfg = ScoringConfig(baseline=0, weights={"verified": 100})
    # verified=True -> +100 clipped
    s = SupplierSignals(verified=True, years_in_business=5, rating_avg=4, reviews_count=50)
    assert assess(s, cfg.model_copy(update={"min_signals": 1})).band == TrustBand.GREEN
    for baseline, band in [(75, TrustBand.GREEN), (74, TrustBand.YELLOW), (50, TrustBand.YELLOW), (49, TrustBand.RED)]:
        c = ScoringConfig(baseline=baseline, weights={}, min_signals=1)
        assert assess(SupplierSignals(verified=True), c).band == band


def test_sanctions_cap_forces_red():
    a = assess(CURATED["sup_demo_sanctioned"], CFG)
    assert a.score <= 20 and a.band == TrustBand.RED and "sanctions_hit" in a.caps_applied


def test_sanctions_red_even_with_no_other_data():
    a = assess(SupplierSignals(sanctions_hit=True), CFG)
    assert a.band == TrustBand.RED and a.score <= 20


@pytest.mark.parametrize(("rate", "cap"), [(0.09, 69), (0.2, 49)])
def test_dispute_cap(rate, cap):
    a = assess(CURATED["sup_demo_gold"].model_copy(update={"dispute_rate": rate}), CFG)
    assert a.score <= cap and "dispute_rate_cap" in a.caps_applied


def test_unknown_band_when_few_signals():
    a = assess(SupplierSignals(verified=True, rating_avg=5), CFG)
    assert a.band == TrustBand.UNKNOWN and a.insufficient_signals
    assert assess(SupplierSignals(), CFG).band == TrustBand.UNKNOWN


def test_score_invariant_and_bilingual():
    for sid in ["sup_cn_001", "sup_demo_avg", "sup_demo_scam", "sup_demo_gold"]:
        sig = CURATED.get(sid) or signals_from_hash(sid)
        a = assess(sig, CFG)
        from ff_trust.domain.models import FactorKind

        signal_sum = sum(f.impact for f in a.factors if f.kind == FactorKind.SIGNAL)
        cap_sum = sum(f.impact for f in a.factors if f.kind == FactorKind.CAP)
        assert a.score == max(0, min(100, a.baseline + signal_sum)) + cap_sum
        assert all(f.explanation and f.explanation_ar for f in a.factors)


def test_determinism():
    assert signals_from_hash("sup_cn_001") == signals_from_hash("sup_cn_001")
    assert signals_from_hash("sup_cn_001") != signals_from_hash("sup_cn_002")
    assert assess(signals_from_hash("x"), CFG) == assess(signals_from_hash("x"), CFG)


async def test_curated_profiles_in_expected_bands():
    ad = MockSignalsAdapter()
    expect = {"sup_demo_gold": TrustBand.GREEN, "sup_demo_avg": TrustBand.YELLOW,
              "sup_demo_scam": TrustBand.RED, "sup_demo_sanctioned": TrustBand.RED}  # fmt: skip
    for sid, band in expect.items():
        assert assess(await ad.get_signals(sid), CFG).band == band, sid


def test_hash_suppliers_span_bands_and_stay_valid():
    bands = {assess(signals_from_hash(f"sup_cn_{i:03d}"), CFG).band for i in range(60)}
    assert TrustBand.GREEN in bands and len(bands) >= 2
