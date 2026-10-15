"""30 extra realistic supplier profiles + explainability, stability and seeded monotonicity properties.

Expectations per profile: band (green/yellow/red/unknown), reason codes (factor keys with a negative / positive impact,
caps, flags). Deterministic, no network. `yellow` is the "amber" band.
"""

import copy
import json
import random
from datetime import date
from pathlib import Path

import pytest

from ff_trust.config import ScoringConfig
from ff_trust.domain.models import FactorKind, TrustBand
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import SupplierSignals

TODAY = date(2026, 10, 15)
CFG = ScoringConfig()
PROFILES = json.loads((Path(__file__).parent / "fixtures" / "trust_archetypes_ext.json").read_text())
RANK = {"red": 0, "yellow": 1, "green": 2}


def run(sig: dict, cfg: ScoringConfig = CFG):
    return assess(SupplierSignals(**sig), cfg, TODAY)


def test_fixture_size_and_unique_ids():
    assert len(PROFILES) == 30
    assert len({p["id"] for p in PROFILES}) == 30
    assert {b for p in PROFILES for b in p["expect"]["band"]} == {"green", "yellow", "red", "unknown"}


@pytest.mark.parametrize("p", PROFILES, ids=[p["id"] for p in PROFILES])
def test_profile_expectations(p):
    e, a = p["expect"], run(p["signals"])
    by = {f.key: f for f in a.factors}
    assert a.band.value in e["band"], (a.band, a.score)
    if "score_min" in e:
        assert a.score >= e["score_min"], a.score
    if "score_max" in e:
        assert a.score <= e["score_max"], a.score
    if "conf_max" in e:
        assert a.confidence <= e["conf_max"], a.confidence
    for k in e.get("neg", []):  # reason codes that must explain a lowered score
        assert k in by and by[k].impact < 0, (k, by.get(k))
    for k in e.get("pos", []):
        assert k in by and by[k].impact > 0, (k, by.get(k))
    for k in e.get("not_has", []):
        assert k not in by or by[k].impact <= 0
    for k in e.get("flags", []):
        assert k in a.flags, a.flags
    for k in e.get("not_flags", []):
        assert k not in a.flags
    for k in e.get("caps", []):
        assert k in a.caps_applied, a.caps_applied
    for g in e.get("gap_keys", []):
        assert g in {x.key for x in a.data_gaps}
    if "level" in e:
        assert a.verification_level == e["level"]
    if e.get("not_green"):
        assert a.band is not TrustBand.GREEN
    if "same_as" in e:  # inflated aggregate must score exactly like the honest-size one
        assert a.score == run({**p["signals"], **e["same_as"]}).score
    if "same_band_as_certs" in e:  # junk certificate names earn no more than a couple of real ones
        assert a.score <= run({**p["signals"], "certifications": e["same_band_as_certs"]}).score + 3


@pytest.mark.parametrize("p", PROFILES, ids=[p["id"] for p in PROFILES])
def test_scoring_is_explainable(p):
    """score == clamp(baseline + sum(signal impacts)) + sum(cap impacts); every cap and band has a reason line."""
    a = run(p["signals"])
    sig_sum = sum(f.impact for f in a.factors if f.kind is FactorKind.SIGNAL)
    cap_sum = sum(f.impact for f in a.factors if f.kind is FactorKind.CAP)
    assert a.score == max(0, min(100, a.baseline + sig_sum)) + cap_sum
    assert all(f.impact <= 0 for f in a.factors if f.kind is FactorKind.CAP)
    keys = {f.key for f in a.factors if f.kind is FactorKind.CAP}
    assert set(a.caps_applied) <= keys
    assert all(f.explanation.strip() and f.explanation_ar.strip() for f in a.factors)
    if a.band is TrustBand.RED and a.score < CFG.yellow_min:  # a red verdict is never unexplained
        assert any(f.impact < 0 for f in a.factors) or a.caps_applied
    if a.band is TrustBand.UNKNOWN:
        assert any(f.key == "insufficient_data" for f in a.factors)
    assert [f.key for f in a.factors] == [f.key for f in run(p["signals"]).factors]  # stable order


@pytest.mark.parametrize("p", PROFILES, ids=[p["id"] for p in PROFILES])
def test_stable_under_key_order_and_repetition(p):
    sig = p["signals"]
    shuffled = dict(reversed(list(sig.items())))
    a, b, c = run(sig), run(shuffled), run(copy.deepcopy(sig))
    assert (a.score, a.band, a.confidence, a.flags, a.caps_applied) == (b.score, b.band, b.confidence, b.flags, b.caps_applied)
    assert (a.score, a.confidence) == (c.score, c.confidence)


# ---------- seeded monotonicity properties ----------

_LIC = ["mismatch", "expired", "unverified", "pending", "verified"]


def _random_profile(rng: random.Random) -> dict:
    s: dict = {}

    def maybe(k, v, p=0.65):
        if rng.random() < p:
            s[k] = v

    maybe("years_in_business", round(rng.uniform(0, 25), 1))
    maybe("verified", rng.random() < 0.6)
    maybe("third_party_audit", rng.random() < 0.3)
    maybe("transactions_count", rng.randint(0, 3000))
    maybe("response_rate", round(rng.random(), 2))
    maybe("rating_avg", round(rng.uniform(2.5, 4.8), 1))
    s["reviews_count"] = rng.randint(0, 400) if "rating_avg" in s else s.get("reviews_count", 0)
    maybe("dispute_rate", round(rng.uniform(0, 0.2), 3))
    maybe("dispute_rate_recent", round(rng.uniform(0, 0.3), 3), 0.3)
    maybe("certifications", rng.sample(["ISO9001", "ISO14001", "CE", "UL", "FDA"], rng.randint(0, 3)))
    maybe("domain_age_years", round(rng.uniform(0, 20), 1))
    maybe("storefront_age_years", round(rng.uniform(0, 15), 1))
    maybe("has_physical_address", rng.random() < 0.7)
    maybe("contact_consistency", round(rng.random(), 2))
    maybe("sanctions_hit", False, 0.8)
    maybe("price_vs_market_ratio", round(rng.uniform(0.3, 2.8), 2))
    maybe("country_risk", round(rng.random(), 2))
    maybe("business_license_status", rng.choice(_LIC))
    maybe("repeat_buyer_rate", round(rng.random(), 2))
    maybe("response_time_hours", round(rng.uniform(0, 120), 1))
    maybe("refund_rate", round(rng.uniform(0, 0.2), 3))
    maybe("deals_completed", rng.randint(0, 80), 0.5)
    maybe("deals_cancelled", rng.randint(0, 40), 0.5)
    maybe("confirmed_reports", rng.randint(0, 4), 0.3)
    if rng.random() < 0.4:
        s["verification"] = {"documents": [{"doc_type": rng.choice(["business_license", "bank_reference", "factory_photos"]), "approved_on": "2026-05-01", "expires_on": "2028-05-01"}]}
    return s


def _improve(s: dict, rng: random.Random) -> dict | None:
    """One strictly-better-evidence edit (never touches review count/rating: those are suspicion-sensitive)."""
    t = copy.deepcopy(s)
    opts = []
    if t.get("verified") is not True:
        opts.append(lambda: t.__setitem__("verified", True))
    if t.get("third_party_audit") is not True:
        opts.append(lambda: t.__setitem__("third_party_audit", True))
    if t.get("has_physical_address") is not True:
        opts.append(lambda: t.__setitem__("has_physical_address", True))
    if t.get("business_license_status") in _LIC[:-1]:
        i = _LIC.index(t["business_license_status"])
        opts.append(lambda: t.__setitem__("business_license_status", _LIC[rng.randint(i + 1, len(_LIC) - 1)]))
    for k, step in (("years_in_business", 1.5), ("domain_age_years", 1.0), ("storefront_age_years", 1.0)):
        if k in t:
            opts.append(lambda k=k, step=step: t.__setitem__(k, round(t[k] + step * rng.random() * 3, 2)))
    if "transactions_count" in t:
        opts.append(lambda: t.__setitem__("transactions_count", t["transactions_count"] + rng.randint(1, 500)))
    for k in ("response_rate", "contact_consistency", "repeat_buyer_rate"):
        if k in t:
            opts.append(lambda k=k: t.__setitem__(k, round(min(1.0, t[k] + rng.random() * 0.3), 3)))
    for k in ("dispute_rate", "dispute_rate_recent", "refund_rate", "country_risk", "response_time_hours", "deals_cancelled", "confirmed_reports"):
        if k in t and t[k]:
            opts.append(lambda k=k: t.__setitem__(k, type(t[k])(t[k] * rng.random())))
    if "deals_completed" in t:
        opts.append(lambda: t.__setitem__("deals_completed", t["deals_completed"] + rng.randint(1, 50)))
    if "price_vs_market_ratio" in t and t["price_vs_market_ratio"] != 1.0:
        def toward_one():
            r = t["price_vs_market_ratio"]
            t["price_vs_market_ratio"] = round(min(1.0, r + 0.2) if r < 1 else max(1.0, r - 0.3), 2)
        opts.append(toward_one)
    if t.get("sanctions_hit") is None:
        opts.append(lambda: t.__setitem__("sanctions_hit", False))
    def add_cert():
        t["certifications"] = [*(t.get("certifications") or []), rng.choice(["ISO45001", "GMP", "BSCI"])]
    opts.append(add_cert)
    def add_doc():
        docs = list((t.get("verification") or {}).get("documents", []))
        docs.append({"doc_type": rng.choice(["company_registry_reference", "export_license", "iso_certificate", "other_certificate"]), "approved_on": "2026-06-01", "expires_on": "2028-06-01"})
        t["verification"] = {"documents": docs}
    opts.append(add_doc)
    rng.choice(opts)()
    return t


@pytest.mark.parametrize("seed", range(8))
def test_more_verified_evidence_never_lowers_score(seed):
    rng = random.Random(1000 + seed)
    for _ in range(120):
        base = _random_profile(rng)
        cur = base
        prev = run(cur)
        for _step in range(4):
            cur = _improve(cur, rng)
            now = run(cur)
            assert now.score >= prev.score, (prev.score, now.score, json.dumps(cur, sort_keys=True))
            if prev.band is not TrustBand.UNKNOWN and now.band is not TrustBand.UNKNOWN:
                assert RANK[now.band.value] >= RANK[prev.band.value]
            prev = now


@pytest.mark.parametrize("seed", range(4))
def test_dropping_a_known_signal_never_raises_confidence_and_never_changes_hard_fail(seed):
    rng = random.Random(2000 + seed)
    for _ in range(80):
        s = _random_profile(rng)
        full = run(s)
        for k in list(s):
            part = run({kk: v for kk, v in s.items() if kk != k})
            assert part.confidence <= full.confidence, k


@pytest.mark.parametrize("seed", range(4))
def test_random_profiles_are_deterministic_bounded_and_hard_fail_is_red(seed):
    rng = random.Random(3000 + seed)
    for _ in range(100):
        s = _random_profile(rng)
        a, b = run(s), run(s)
        assert (a.score, a.band, a.confidence, a.flags) == (b.score, b.band, b.confidence, b.flags)
        assert 0 <= a.score <= 100 and 0 <= a.confidence <= 100
        if a.band is TrustBand.GREEN:
            assert a.score >= CFG.green_min and not a.caps_applied
        worse = run({**s, "sanctions_hit": True})
        assert worse.band is TrustBand.RED and worse.score <= CFG.sanctions_cap
        assert run({**s, "blocked": True}).band is TrustBand.RED


def test_more_cancelled_deals_never_raise_score():
    base = dict(PROFILES[1]["signals"])
    prev = 101
    for canc in range(0, 120, 3):
        sc = run({**base, "deals_completed": 40, "deals_cancelled": canc}).score
        assert sc <= prev
        prev = sc
