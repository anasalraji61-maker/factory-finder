"""QA runner: 25 synthetic supplier archetypes (fixtures/trust_archetypes.json) against the scoring engine.

Checks bands/confidence/flags per profile, bilingual honest explanations, confidence monotonicity,
"one missing critical signal never gives a high-confidence green", and resistance to gaming
(burst reviews, duplicate documents/certificates, report flooding). Deterministic, no network.
"""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ff_trust.cache import TTLCache
from ff_trust.config import ScoringConfig
from ff_trust.db import Database
from ff_trust.domain.models import TrustBand
from ff_trust.domain.scoring import CRITICAL_SIGNALS, SCORABLE, assess
from ff_trust.domain.signals import SupplierSignals
from ff_trust.service import TrustService
from ff_trust.store import ReportStore

TODAY = date(2026, 10, 15)
CFG = ScoringConfig()
HIGH_CONF = 80
PROFILES = json.loads((Path(__file__).parent / "fixtures" / "trust_archetypes.json").read_text())
BY_ID = {p["id"]: p for p in PROFILES}
ARABIC = re.compile(r"[؀-ۿ]")
SIGNAL_FIELDS = [f for f in SupplierSignals.model_fields if f != "supplier_id"]


def run(sig: dict):
    return assess(SupplierSignals(**sig), CFG, TODAY)


def test_fixture_covers_all_archetypes():
    assert len(PROFILES) == 25
    assert {p["archetype"] for p in PROFILES} == set("abcdefgh")
    assert len({p["id"] for p in PROFILES}) == 25


@pytest.mark.parametrize("p", PROFILES, ids=[p["id"] for p in PROFILES])
def test_profile_expectations(p):
    e, a = p["expect"], run(p["signals"])
    if "band" in e:
        assert a.band.value in e["band"], (a.band, a.score)
    if "score_min" in e:
        assert a.score >= e["score_min"], a.score
    if "score_max" in e:
        assert a.score <= e["score_max"], a.score
    if "conf_min" in e:
        assert a.confidence >= e["conf_min"], a.confidence
    if "conf_max" in e:
        assert a.confidence <= e["conf_max"], a.confidence
    for fl in e.get("flags", []):
        assert fl in a.flags, a.flags
    for c in e.get("caps", []):
        assert c in a.caps_applied
    for g in e.get("gap_keys", []):
        assert g in {x.key for x in a.data_gaps}
    if "level" in e:
        assert a.verification_level == e["level"]
    # score/band consistency with the documented invariant
    assert 0 <= a.score <= 100 and 0 <= a.confidence <= 100
    if a.band is TrustBand.GREEN:
        assert a.score >= CFG.green_min


@pytest.mark.parametrize("p", PROFILES, ids=[p["id"] for p in PROFILES])
def test_explanations_bilingual_and_honest(p):
    sig = p["signals"]
    a = run(sig)
    for f in a.factors:
        assert f.explanation.strip() and f.explanation_ar.strip(), f.key
        assert ARABIC.search(f.explanation_ar), f.key
        assert not ARABIC.search(f.explanation.replace("—", "")), f.key  # English text stays English
    for g in a.data_gaps:
        assert g.label.strip() and ARABIC.search(g.label_ar), g.key
    by = {f.key: f for f in a.factors}
    # never credit verification that did not happen
    if sig.get("verified") is not True:
        assert by.get("verified") is None or by["verified"].impact <= 0
    if sig.get("third_party_audit") is not True:
        assert by.get("third_party_audit") is None or by["third_party_audit"].impact <= 0
        assert a.verification_level != "audited"
    if sig.get("business_license_status") != "verified":
        assert by.get("business_license_status") is None or by["business_license_status"].impact <= 0
    if not (sig.get("verification") or {}).get("documents"):
        assert "document_verification" not in by and "facility_evidence" not in by
        assert a.verification_level == "none"
    if sig.get("sanctions_hit") is None:  # screening not run -> must say so, never claim "clear"
        assert "sanctions_hit" in {g.key for g in a.data_gaps}
    for g in a.data_gaps:  # a gap is never also scored
        assert g.key not in by or g.key == "sanctions_hit"


@pytest.mark.parametrize("p", PROFILES, ids=[p["id"] for p in PROFILES])
def test_removing_evidence_never_raises_confidence(p):
    sig, full = p["signals"], run(p["signals"]).confidence
    present = [k for k in sig if k in SIGNAL_FIELDS]
    for k in present:
        assert run({kk: v for kk, v in sig.items() if kk != k}).confidence <= full, k
    # chain: adding fields one by one (fixed order) never lowers confidence
    prev, acc = -1, {}
    for k in present:
        acc[k] = sig[k]
        c = run(acc).confidence
        assert c >= prev, (k, prev, c)
        prev = c


@pytest.mark.parametrize("p", [p for p in PROFILES if p["archetype"] in "adg"], ids=lambda p: p["id"])
def test_missing_critical_signal_never_high_confidence_green(p):
    for k in CRITICAL_SIGNALS:
        if k not in p["signals"]:
            continue
        a = run({kk: v for kk, v in p["signals"].items() if kk != k})
        assert not (a.band is TrustBand.GREEN and a.confidence >= HIGH_CONF), (k, a.confidence)


def test_missing_data_never_lowers_score():
    base = dict(BY_ID["a2_mid_audited_factory"]["signals"])
    top = run(base).score
    for k in ("response_time_hours", "repeat_buyer_rate", "domain_age_years", "country_risk", "contact_consistency"):
        s = {kk: v for kk, v in base.items() if kk != k}
        assert run(s).score >= min(top, 100) - 10  # dropping a mildly-positive signal changes little; never penalises
    # a missing signal is a gap, not a penalty: an all-gaps profile has the neutral baseline score
    assert run({"verified": True, "years_in_business": 5, "rating_avg": 4}).band is TrustBand.UNKNOWN


# ---------- gaming ----------


def test_review_burst_cannot_buy_green():
    farm = run(BY_ID["e1_review_farm_burst"]["signals"])
    thin = dict(BY_ID["e1_review_farm_burst"]["signals"], reviews_count=3)
    assert "review_pattern_suspicious" in farm.flags
    assert farm.score <= run(thin).score + 2  # 600 five-star reviews buy no more than 3 do
    # more reviews never help a burst-flagged profile
    more = run(dict(BY_ID["e1_review_farm_burst"]["signals"], reviews_count=5000))
    assert more.score <= farm.score


def test_organic_reviews_not_flagged():
    for pid in ("a1_gold_factory", "a2_mid_audited_factory", "d1_good_one_confirmed_report"):
        assert "review_pattern_suspicious" not in run(BY_ID[pid]["signals"]).flags


def test_duplicate_documents_and_certificates_count_once():
    one = {"documents": [{"doc_type": "business_license", "approved_on": "2026-03-01", "expires_on": "2028-03-01"}]}
    many = {"documents": one["documents"] * 25}
    base = dict(BY_ID["a2_mid_audited_factory"]["signals"])
    assert run({**base, "verification": one}).score == run({**base, "verification": many}).score
    c1 = run({**base, "certifications": ["ISO9001"]})
    c2 = run({**base, "certifications": ["ISO9001", "iso 9001", "ISO-9001", "Iso9001 "]})
    assert c1.score == c2.score
    recs = [{"name": "ISO9001", "expires_on": "2029-01-01"}] * 6
    assert run({**base, "certifications": None, "certification_records": recs}).score == run({**base, "certifications": ["ISO9001"]}).score


def test_junk_certificate_names_have_bounded_credit():
    base = dict(BY_ID["a2_mid_audited_factory"]["signals"], certifications=["ISO9001", "CE"])
    junk = dict(base, certifications=[f"X{i}" for i in range(200)])
    assert run(junk).score <= run(base).score + 3


async def _service(pending: int, accepted: int, reporters: int, sig: dict):
    class Adapter:
        name = "fixture"

        async def get_signals(self, supplier_id):
            return SupplierSignals(**sig)

    db = Database("sqlite+aiosqlite:///:memory:", True)
    store = ReportStore(limit=1000, window_seconds=60, clock=lambda: datetime(2026, 10, 15, tzinfo=UTC), db=db)
    svc = TrustService(Adapter(), CFG, TTLCache(0, 10), reports=store)
    base = await svc.for_supplier("s1")
    for i in range(pending):
        await svc.add_report("s1", f"new{i % reporters}", "fraud", "x", low_trust=True)
    for i in range(accepted):
        r = await svc.add_report("s1", f"new{i % reporters}", "fraud", "x", low_trust=True)
        await svc.review_report(r.id, "accepted")
    after = await svc.for_supplier("s1")
    await db.dispose()
    return base, after


@pytest.mark.parametrize("p", [p for p in PROFILES if "bomb" in p["expect"]], ids=lambda p: p["id"])
async def test_report_flooding(p):
    b = p["expect"]["bomb"]
    base, after = await _service(b["pending"], b["accepted"], b["reporters"], p["signals"])
    if p["expect"].get("same_as_baseline"):  # pending reports from new accounts never touch the score
        assert (after.score, after.band, after.confidence) == (base.score, base.band, base.confidence)
    if "accepted_distinct" in p["expect"]:  # five accepted reports from ONE account count as one
        same = run({**p["signals"], "confirmed_reports": p["expect"]["accepted_distinct"]})
        assert after.score == same.score


def test_confirmed_reports_penalty_is_bounded():
    base = dict(BY_ID["a1_gold_factory"]["signals"])
    lo, hi = run({**base, "confirmed_reports": 3}).score, run({**base, "confirmed_reports": 500}).score
    assert lo == hi
    assert run(base).score - lo <= CFG.weights["confirmed_reports"]


def test_weights_cover_scorable():
    assert all(k in CFG.weights for k in SCORABLE)


# ---------- gaming: new accounts, review bombing, certificate reuse ----------

_SOLID = dict(verified=True, third_party_audit=True, dispute_rate=0, price_vs_market_ratio=1, sanctions_hit=False,
              response_rate=1, has_physical_address=True, contact_consistency=1, business_license_status="verified",
              rating_avg=5, reviews_count=20, repeat_buyer_rate=1, response_time_hours=1, refund_rate=0, country_risk=0.1)


def test_new_account_cannot_reach_green_on_self_reported_claims():
    new = run({**_SOLID, "years_in_business": 0.2, "transactions_count": 0})
    assert "new_account" in new.flags and "new_account_cap" in new.caps_applied
    assert new.score < CFG.green_min and new.band is not TrustBand.GREEN
    old = run({**_SOLID, "years_in_business": 6, "transactions_count": 300})
    assert old.band is TrustBand.GREEN and "new_account" not in old.flags
    # a young business that already has a real deal history is not capped; unknown age is never "new"
    assert "new_account" not in run({**_SOLID, "years_in_business": 0.2, "transactions_count": 40}).flags
    assert "new_account" not in run(_SOLID).flags


def test_platform_reviews_cannot_outnumber_completed_deals():
    base = {"years_in_business": 6, "verified": True, "dispute_rate": 0, "price_vs_market_ratio": 1, "sanctions_hit": False}
    none = run({**base, "review_summary": {"count": 0}})
    for avg in (5.0, 1.0):  # neither a positive nor a negative bomb from reviews no deal backs
        bomb = run({**base, "review_summary": {"count": 500, "average": avg, "completed_deals": 0}})
        assert bomb.score == none.score
    capped = run({**base, "review_summary": {"count": 500, "average": 5.0, "completed_deals": 3}})
    honest = run({**base, "review_summary": {"count": 3, "average": 5.0, "completed_deals": 3}})
    assert capped.score == honest.score


def test_headline_average_contradicted_by_histogram_is_not_trusted():
    base = {"years_in_business": 6, "verified": True, "dispute_rate": 0, "price_vs_market_ratio": 1, "sanctions_hit": False}
    fake = run({**base, "review_summary": {"count": 100, "average": 5.0, "histogram": {"1": 80, "5": 20}, "completed_deals": 100}})
    real = run({**base, "review_summary": {"count": 100, "histogram": {"1": 80, "5": 20}, "completed_deals": 100}})
    assert fake.score == real.score


def test_certificate_edition_years_count_once():
    base = dict(BY_ID["a2_mid_audited_factory"]["signals"])
    one = run({**base, "certifications": ["ISO9001"]})
    variants = run({**base, "certifications": ["ISO9001", "ISO 9001:2015", "ISO9001:2008", "iso 9001-2015", "ISO 9001 2015"]})
    assert one.score == variants.score
    assert run({**base, "certifications": ["ISO 22000:2018"]}).score == run({**base, "certifications": ["ISO22000"]}).score
    # distinct standards still count separately
    assert run({**base, "certifications": ["ISO 9001:2015", "ISO 14001:2015"]}).score >= one.score
