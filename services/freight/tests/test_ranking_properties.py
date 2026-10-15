"""Seeded property tests for the pure ranking (no hypothesis dependency)."""

import random
from decimal import Decimal

import pytest

from ff_freight.ranking import Candidate, normalise_weights, rank, rating_confidence

W = normalise_weights(50, 30, 20)
MODES = ("score", "price", "transit", "rating")


def _cands(rng, n):
    return [
        Candidate(f"q{i:03d}", Decimal(rng.randint(100, 5000)) / 4, rng.randint(1, 60),
                  (c := rng.randint(0, 30)) * rng.randint(1, 5), c, f"2026-01-01T00:00:{rng.randint(0, 5):02d}")
        for i in range(n)
    ]


@pytest.mark.parametrize("seed", range(25))
def test_properties(seed):
    rng = random.Random(seed)
    cs = _cands(rng, rng.randint(1, 12))
    for mode in MODES:
        a = rank(list(cs), W, mode)
        shuffled = list(cs)
        rng.shuffle(shuffled)
        b = rank(shuffled, W, mode)
        assert [r["quote_id"] for r in a] == [r["quote_id"] for r in b]  # deterministic, input-order independent
        assert sorted(r["quote_id"] for r in a) == sorted(c.quote_id for c in cs)  # nothing dropped
        assert [r["rank"] for r in a] == list(range(1, len(cs) + 1))
        assert all(Decimal(0) <= r["score"] <= Decimal(100) for r in a)
    cheapest = min(c.amount for c in cs)
    by = {r["quote_id"]: r for r in rank(cs, W)}
    for c in cs:
        r = by[c.quote_id]
        assert ("cheapest" in r["badges"]) == (c.amount == cheapest)
        assert r["cheaper_quote_ids"] == sorted(
            (x.quote_id for x in cs if x.amount < c.amount), key=lambda q: (next(x.amount for x in cs if x.quote_id == q), q)
        )
        assert r["price_delta"] == c.amount - cheapest
        if "top_rated" in r["badges"]:
            assert c.rating_count >= 5
    prices = [r["quote_id"] for r in rank(cs, W, "price")]
    amounts = {c.quote_id: c.amount for c in cs}
    assert [amounts[q] for q in prices] == sorted(amounts.values())  # price sort never hides/reorders a cheaper quote


def test_rating_shrinkage_and_anti_gaming():
    lone = Candidate("a", Decimal(100), 10, 5, 1, "k")  # one 5-star
    solid = Candidate("b", Decimal(100), 10, 4 * 40, 40, "k")  # forty 4-star
    rows = {r["quote_id"]: r for r in rank([lone, solid], W, "rating")}
    assert rows["b"]["rank"] == 1 and "top_rated" not in rows["a"]["badges"]
    assert [rating_confidence(n) for n in (0, 1, 4, 5)] == ["unrated", "low", "low", "established"]
    assert any("low confidence" in e for e in rows["a"]["explanation"])


def test_comparison_shows_diff_verification_and_expired_terms(client):
    from conftest import make_forwarder, make_quote, make_request, uh

    for u in ("f1", "f2"):
        make_forwarder(client, u)
    req = make_request(client)
    make_quote(client, req["id"], "f1", amount="1000", transit_days=30, inclusions=["Customs clearance", "THC"])
    make_quote(client, req["id"], "f2", amount="900", transit_days=30, inclusions=["THC"])
    body = client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()
    assert len(body["items"]) == 2
    cheap = next(i for i in body["items"] if i["quote"]["amount"] == "900.00")
    dear = next(i for i in body["items"] if i["quote"]["amount"] == "1000.00")
    assert cheap["inclusions_missing"] == ["Customs clearance"] and dear["inclusions_unique"] == ["Customs clearance"]
    assert dear["cheaper_quote_ids"] == [cheap["quote"]["id"]] and dear["price_delta"] == 100.0
    assert dear["rating_confidence"] == "unrated" and isinstance(dear["verified"], bool) and dear["valid_until"]
