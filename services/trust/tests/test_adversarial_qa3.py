"""Property-style scoring tests (parametrized; hypothesis is not a dependency): monotonicity, bounds, determinism,
robustness to empty / oversized evidence."""

import random
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from ff_trust.config import ScoringConfig
from ff_trust.domain.models import TrustBand
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import CertificationRecord, SupplierSignals
from ff_trust.domain.verification import VerificationEvidence, VerifiedDoc

CFG = ScoringConfig()
TODAY = date(2026, 6, 1)
BASE = dict(years_in_business=5, verified=True, transactions_count=100, rating_avg=4.0, reviews_count=50)
CERTS = ["ISO9001", "ISO14001", "CE", "UL", "FDA", "SGS", "RoHS", "REACH", "BSCI", "GMP"]


def sc(**kw):
    return assess(SupplierSignals(**{**BASE, **kw}), CFG, TODAY).score


def doc(t, **kw):
    return VerifiedDoc(doc_type=t, approved_on=TODAY - timedelta(days=30), **kw)


# ------------------------------------------------------------------------------------ monotonicity
@pytest.mark.parametrize("base", [{}, {"deals_completed": 20}, {"years_in_business": 0.2, "transactions_count": 0}])
def test_more_verified_certs_never_lowers_score(base):
    prev = sc(certifications=[], **base)
    for n in range(1, len(CERTS) + 1):
        cur = sc(certifications=CERTS[:n], **base)
        assert cur >= prev
        prev = cur


def test_more_dated_valid_cert_records_never_lowers_score():
    recs = [CertificationRecord(name=n, expires_on=TODAY + timedelta(days=400)) for n in CERTS]
    prev = sc(certification_records=[])
    for n in range(1, len(recs) + 1):
        cur = sc(certification_records=recs[:n])
        assert cur >= prev
        prev = cur


def test_expired_certs_never_help_and_valid_ones_never_hurt():
    exp = [CertificationRecord(name=n, expires_on=TODAY - timedelta(days=1)) for n in CERTS]
    assert sc(certification_records=exp) <= sc(certification_records=[])  # lapsed-only is penalised by design
    assert sc(certification_records=exp[:3]) <= sc(
        certification_records=[CertificationRecord(name=n, expires_on=TODAY + timedelta(days=500)) for n in CERTS[:3]]
    )


@pytest.mark.parametrize("completed", [0, 1, 5, 20, 200])
def test_more_cancellations_never_raises_score(completed):
    prev = sc(deals_completed=completed, deals_cancelled=0)
    for c in range(1, 300):
        cur = sc(deals_completed=completed, deals_cancelled=c)
        assert cur <= prev, (completed, c)
        prev = cur


@pytest.mark.parametrize("completed", [0, 10, 100])
def test_more_completed_deals_never_lowers_score(completed):
    prev = sc(deals_completed=0, deals_cancelled=completed // 5)
    for d in (1, 5, 20, 100, 1000):
        cur = sc(deals_completed=d, deals_cancelled=completed // 5)
        assert cur >= prev
        prev = cur


@pytest.mark.parametrize(
    ("field", "worse", "better"),
    [
        ("confirmed_reports", [5, 3, 1, 0], None),
        ("dispute_rate", [0.5, 0.3, 0.1, 0.05, 0.0], None),
        ("dispute_rate_recent", [0.5, 0.2, 0.05, 0.0], None),
        ("refund_rate", [0.6, 0.3, 0.1, 0.0], None),
        ("country_risk", [1.0, 0.7, 0.3, 0.0], None),
    ],
)
def test_more_bad_signal_never_raises_score(field, worse, better):
    scores = [sc(**{field: v}) for v in worse]  # ordered worst -> best
    assert scores == sorted(scores)


def test_more_verified_documents_never_lowers_score():
    types = ["business_license", "company_registry_reference", "bank_reference", "export_license",
             "factory_photos", "iso_certificate", "other_certificate"]  # fmt: skip
    prev = sc(verification=VerificationEvidence(documents=[]))
    for n in range(1, len(types) + 1):
        cur = sc(verification=VerificationEvidence(documents=[doc(t) for t in types[:n]]))
        assert cur >= prev
        prev = cur


def test_hard_flags_only_lower():
    assert sc(sanctions_hit=True) <= sc(sanctions_hit=False) <= sc()
    assert sc(blocked=True) <= sc(blocked=False)


# ------------------------------------------------------------------------------------------ bounds
def _random_signals(rng: random.Random) -> SupplierSignals:
    def f(lo, hi):
        return rng.choice([None, rng.uniform(lo, hi), lo, hi])

    def i(hi):
        return rng.choice([None, rng.randint(0, hi), 0, hi])

    def b():
        return rng.choice([None, True, False])

    return SupplierSignals(
        years_in_business=f(0, 200), verified=b(), third_party_audit=b(), transactions_count=i(10**9),
        response_rate=f(0, 1), rating_avg=f(0, 5), reviews_count=i(10**9), dispute_rate=f(0, 1),
        certifications=rng.choice([None, [], rng.sample(CERTS, rng.randint(0, len(CERTS)))]),
        domain_age_years=f(0, 100), has_physical_address=b(), contact_consistency=f(0, 1), sanctions_hit=b(),
        price_vs_market_ratio=rng.choice([None, 1e-9, 0.01, 0.5, 1, 3, 1e9]), country_risk=f(0, 1),
        business_license_status=rng.choice([None, "verified", "pending", "unverified", "expired", "mismatch"]),
        storefront_age_years=f(0, 100), repeat_buyer_rate=f(0, 1), response_time_hours=f(0, 8760),
        dispute_rate_recent=f(0, 1), refund_rate=f(0, 1), deals_completed=i(10**9), deals_cancelled=i(10**9),
        confirmed_reports=i(10**6), blocked=b(),
    )  # fmt: skip


def test_random_signals_bounded_deterministic_consistent():
    rng = random.Random(99)
    for _ in range(600):
        s = _random_signals(rng)
        a, b = assess(s, CFG, TODAY), assess(s, CFG, TODAY)
        assert a == b
        assert isinstance(a.score, int) and 0 <= a.score <= 100
        assert 0 <= a.confidence <= 100
        assert a.band in set(TrustBand)
        assert a.signals_used <= a.signals_total
        if s.sanctions_hit or s.blocked:
            assert a.band == TrustBand.RED and a.score <= 20 or a.band == TrustBand.RED
        assert all(isinstance(f.impact, int) for f in a.factors)
        if a.band == TrustBand.GREEN:
            assert a.score >= CFG.green_min


def test_signal_field_order_and_construction_path_do_not_matter():
    d = {**BASE, "response_rate": 0.9, "dispute_rate": 0.01}
    a = assess(SupplierSignals(**d), CFG, TODAY)
    b = assess(SupplierSignals(**dict(reversed(list(d.items())))), CFG, TODAY)
    c = assess(SupplierSignals.model_validate_json(SupplierSignals(**d).model_dump_json()), CFG, TODAY)
    assert a == b == c


# ------------------------------------------------------------------------------ empty / oversized
def test_empty_signals_do_not_crash_and_are_unknown():
    a = assess(SupplierSignals(), CFG, TODAY)
    assert 0 <= a.score <= 100 and a.band == TrustBand.UNKNOWN and a.insufficient_signals


@pytest.mark.parametrize(
    "kw",
    [
        {"certifications": []},
        {"certification_records": []},
        {"verification": VerificationEvidence()},
        {"certifications": ["x" * 64] * 200},
        {"certifications": [f"CERT{i}" for i in range(200)]},
        {"certification_records": [CertificationRecord(name=f"C{i}", expires_on=TODAY) for i in range(200)]},
        {"certifications": ["  ", "---", "ISO 9001:2015", "iso9001", "ISO-9001"]},
        {"certifications": ["شهادة الجودة", "🏭", "\u0000"]},
        {"transactions_count": 10**15, "reviews_count": 10**15, "deals_completed": 10**15, "deals_cancelled": 10**15},
        {"verification": VerificationEvidence(documents=[doc("business_license")] * 5000)},
        {"verification": VerificationEvidence(documents=[doc("iso_certificate", expires_on=date(9999, 12, 31))])},
        {"verification": VerificationEvidence(documents=[doc("bank_reference", expires_on=date(1, 1, 1))])},
    ],
)
def test_extreme_evidence_does_not_crash(kw):
    a = assess(SupplierSignals(**kw), CFG, TODAY)
    assert 0 <= a.score <= 100


def test_duplicate_certs_and_docs_are_not_double_counted():
    one = sc(certifications=["ISO9001"])
    assert sc(certifications=["ISO9001", "iso 9001", "ISO-9001:2015", "ISO9001"]) == one
    d1 = sc(verification=VerificationEvidence(documents=[doc("business_license")]))
    assert sc(verification=VerificationEvidence(documents=[doc("business_license")] * 500)) <= d1 + 3


def test_oversized_lists_rejected_at_the_boundary():
    with pytest.raises(ValidationError):
        SupplierSignals(certifications=["ISO"] * 201)
    with pytest.raises(ValidationError):
        SupplierSignals(certifications=["x" * 65])
    with pytest.raises(ValidationError):
        SupplierSignals(certification_records=[CertificationRecord(name="a")] * 201)


@pytest.mark.parametrize(
    "kw",
    [
        {"response_rate": float("nan")}, {"rating_avg": float("inf")}, {"years_in_business": -1},
        {"dispute_rate": 1.0001}, {"price_vs_market_ratio": 0}, {"deals_cancelled": -1},
        {"price_vs_market_ratio": float("nan")}, {"country_risk": float("nan")},
    ],
)  # fmt: skip
def test_invalid_numbers_rejected_not_scored(kw):
    with pytest.raises(ValidationError):
        SupplierSignals(**kw)
