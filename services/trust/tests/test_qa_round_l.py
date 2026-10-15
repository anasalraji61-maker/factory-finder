"""QA round L: explainability (ar+en per factor), history timestamp order, stale-evidence decay boundaries."""

import re
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_trust.config import ScoringConfig, Settings
from ff_trust.domain.models import FactorKind
from ff_trust.domain.scoring import SCORABLE, assess
from ff_trust.domain.signals import CertificationRecord, ReviewSummary, SupplierSignals
from ff_trust.domain.verification import VerificationEvidence, VerifiedDoc, decay, effective_expiry
from ff_trust.main import create_app

CFG = ScoringConfig()
TODAY = date(2026, 10, 15)
AR = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]{3,}")


def full(**over):
    d = dict(
        years_in_business=8, verified=True, third_party_audit=True, transactions_count=300, response_rate=0.9,
        rating_avg=4.5, reviews_count=80, dispute_rate=0.02, dispute_rate_recent=0.01, certifications=["ISO 9001"],
        certification_records=[CertificationRecord(name="CE", expires_on=TODAY + timedelta(days=10)),
                               CertificationRecord(name="FDA", expires_on=TODAY - timedelta(days=1))],
        domain_age_years=6, has_physical_address=True, contact_consistency=0.9, sanctions_hit=False,
        price_vs_market_ratio=0.95, country_risk=0.2, business_license_status="verified",
        storefront_age_years=5, repeat_buyer_rate=0.4, response_time_hours=4, refund_rate=0.01,
        deals_completed=40, deals_cancelled=2, confirmed_reports=1,
        review_summary=ReviewSummary(count=12, average=4.6, completed_deals=20),
        verification=VerificationEvidence(documents=[
            VerifiedDoc(doc_type="business_license", approved_on=TODAY - timedelta(days=100), expires_on=TODAY + timedelta(days=20)),
            VerifiedDoc(doc_type="factory_photos", approved_on=TODAY - timedelta(days=800)),  # default validity lapsed
        ]),
    )  # fmt: skip
    return SupplierSignals(**{**d, **over})


SCENARIOS = {
    "full": full(),
    "sanctioned": full(sanctions_hit=True),
    "blocked": full(blocked=True),
    "cheap": full(price_vs_market_ratio=0.2),
    "dear": full(price_vs_market_ratio=3.0),
    "disputes": full(dispute_rate=0.2),
    "cancelled": full(deals_completed=5, deals_cancelled=30),
    "new": full(years_in_business=0.2, storefront_age_years=0.3, transactions_count=1, deals_completed=1, deals_cancelled=0),
    "bought_reviews": full(rating_avg=5.0, reviews_count=500, transactions_count=10),
    "thin": SupplierSignals(verified=True),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_factor_has_delta_and_both_languages(name):
    a = assess(SCENARIOS[name], CFG, TODAY)
    assert a.factors
    for f in a.factors:
        assert isinstance(f.impact, int) and f.key
        assert f.explanation.strip() and f.explanation_ar.strip(), f.key
        assert AR.search(f.explanation_ar), f"{f.key}: Arabic text has no Arabic letters"
        assert not AR.search(f.explanation), f"{f.key}: English text contains Arabic"
        if f.kind is not FactorKind.INFO:  # info notes carry impact 0 by design
            assert f.impact != 0 or f.kind is FactorKind.SIGNAL
        if f.kind is FactorKind.CAP:
            assert f.impact <= 0
    for g in a.data_gaps:
        assert g.label.strip() and AR.search(g.label_ar)
    # the delta bookkeeping is exact: baseline + signal impacts (clamped) + cap impacts == score
    sig = sum(f.impact for f in a.factors if f.kind is FactorKind.SIGNAL)
    caps = sum(f.impact for f in a.factors if f.kind is FactorKind.CAP)
    assert max(0, min(100, a.baseline + sig)) + caps == a.score or a.band.value == "unknown"


def test_explanation_direction_matches_delta():
    for f in assess(SCENARIOS["full"], CFG, TODAY).factors:
        if f.kind is not FactorKind.SIGNAL:
            continue
        word, word_ar = (("raises", "يرفع") if f.impact > 0 else ("lowers", "يخفض") if f.impact < 0 else ("does not change", "لا يؤثر"))
        assert word in f.explanation and word_ar in f.explanation_ar, f.key


def test_every_scorable_signal_has_both_labels():
    from ff_trust.domain.scoring import LABELS

    assert set(SCORABLE) <= set(LABELS)
    for k, (en, ar) in LABELS.items():
        assert en.strip() and AR.search(ar) and not AR.search(en), k


def test_api_factors_bilingual():
    c = TestClient(create_app(Settings()))
    body = c.post("/v1/trust/evaluate", json=SCENARIOS["full"].model_dump(mode="json")).json()
    for f in body["factors"]:
        assert {"key", "impact", "explanation", "explanation_ar"} <= set(f)
        assert f["explanation"] and AR.search(f["explanation_ar"])


# ---- history
def test_history_timestamps_never_go_backwards_and_unique_per_source():
    c = TestClient(create_app(Settings()))
    for sid in ("sup_demo_avg", "sup_demo_sanctioned"):
        for _ in range(3):  # repeated reads add snapshots only when the score changed
            pts = c.get(f"/v1/trust/suppliers/{sid}/history").json()["points"]
            ats = [datetime.fromisoformat(p["at"].replace("Z", "+00:00")) for p in pts]
            assert all(a <= b for a, b in zip(ats, ats[1:], strict=False))
            mock = [a for a, p in zip(ats, pts, strict=True) if p["source"] == "mock"]
            assert len(set(mock)) == len(mock)
            assert all(a.tzinfo is not None for a in ats)


async def test_history_orders_out_of_order_snapshots():
    from ff_trust.service import TrustService
    from ff_trust.store import Snapshot

    c = TestClient(create_app(Settings()))
    svc: TrustService = c.app.state.service if hasattr(c.app.state, "service") else None
    if svc is None:
        pytest.skip("service not on app.state")
    base = datetime(2026, 10, 1, tzinfo=UTC)
    await svc.snapshots.add("sup_demo_avg", Snapshot(base + timedelta(days=5), 50, "yellow", 60))
    await svc.snapshots.add("sup_demo_avg", Snapshot(base, 61, "yellow", 60))  # clock skew: older arrives later
    pts = (await svc.history("sup_demo_avg")).points
    assert [p.at for p in pts] == sorted(p.at for p in pts)


# ---- stale-evidence decay boundaries
def doc(exp, approved=TODAY - timedelta(days=30)):
    return VerifiedDoc(doc_type="business_license", approved_on=approved, expires_on=exp)


@pytest.mark.parametrize(
    "days_left,expected",
    [(91, 1.0), (90, 1.0), (89, None), (45, None), (1, None), (0, 0.5), (-1, 0.0), (-400, 0.0)],
)
def test_document_decay_boundaries(days_left, expected):
    k = decay(doc(TODAY + timedelta(days=days_left)), TODAY, 90, 0.5, 730)
    if expected is None:
        assert 0.5 < k < 1.0
        assert k == pytest.approx(0.5 + 0.5 * days_left / 90)
    else:
        assert k == expected


def test_document_decay_is_monotonic_across_every_day():
    ks = [decay(doc(TODAY + timedelta(days=d)), TODAY, 90, 0.5, 730) for d in range(-5, 120)]
    assert all(a <= b for a, b in zip(ks, ks[1:], strict=False))


def test_default_validity_and_three_year_cap_boundaries():
    d = VerifiedDoc(doc_type="bank_reference", approved_on=TODAY - timedelta(days=730))
    assert effective_expiry(d, 730) == TODAY and decay(d, TODAY, 90, 0.5, 730) == 0.5  # last valid day
    assert decay(d, TODAY + timedelta(days=1), 90, 0.5, 730) == 0.0
    far = VerifiedDoc(doc_type="bank_reference", approved_on=TODAY - timedelta(days=1095), expires_on=date(2099, 1, 1))
    assert effective_expiry(far, 730) == TODAY and decay(far, TODAY, 90, 0.5, 730) == 0.5
    assert decay(far, TODAY + timedelta(days=1), 90, 0.5, 730) == 0.0


def _doc_flags(exp):
    s = SupplierSignals(verification=VerificationEvidence(documents=[doc(exp)]), **{"verified": True})
    return assess(s, CFG, TODAY)


def test_document_flags_and_level_at_boundary():
    last_day = _doc_flags(TODAY)
    assert "verification_document_expiring" in last_day.flags and "verification_document_expired" not in last_day.flags
    assert last_day.verification_level == "basic"
    gone = _doc_flags(TODAY - timedelta(days=1))
    assert "verification_document_expired" in gone.flags and gone.verification_level == "none"
    assert not any(k.startswith("verification_document") for k in _doc_flags(TODAY + timedelta(days=90)).flags)
    assert "verification_document_expiring" in _doc_flags(TODAY + timedelta(days=89)).flags


def test_document_points_follow_decay():
    pts = {}
    for d in (91, 45, 0, -1):
        a = assess(SupplierSignals(verification=VerificationEvidence(documents=[doc(TODAY + timedelta(days=d))]), verified=True), CFG, TODAY)
        pts[d] = next((f.impact for f in a.factors if f.key == "document_verification"), 0)
    assert pts[91] >= pts[45] >= pts[0] >= pts[-1] == 0


@pytest.mark.parametrize("delta,expired,soon", [(-1, True, False), (0, False, True), (60, False, True), (61, False, False)])
def test_certificate_expiry_boundaries(delta, expired, soon):
    s = SupplierSignals(certification_records=[CertificationRecord(name="ISO 9001", expires_on=TODAY + timedelta(days=delta))])
    flags = assess(s, CFG, TODAY).flags
    assert ("certification_expired" in flags) is expired and ("certification_expiring" in flags) is soon
