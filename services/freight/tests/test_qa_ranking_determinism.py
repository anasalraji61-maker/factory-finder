"""QA round: ranking is a pure, order-independent function with a fully specified tie-break chain."""
import itertools
import random
from decimal import Decimal

import pytest

from ff_freight.ranking import Candidate, normalise_weights, rank

W = normalise_weights(50, 30, 20)
SORTS = ["score", "price", "transit", "rating"]


def c(qid, amount, days, rs=0, rc=0, key="2026-01-01T00:00:00"):
    return Candidate(qid, Decimal(amount), days, rs, rc, key)


def ids(cands, sort="score", w=W):
    return [r["quote_id"] for r in rank(cands, w, sort)]


@pytest.mark.parametrize("sort", SORTS)
def test_order_independent_and_repeatable(sort):
    rng = random.Random(7)
    pool = [c(f"q{i}", str(rng.choice([800, 900, 900, 1000])), rng.choice([10, 20, 20, 30]),
              rng.choice([0, 20, 25]), rng.choice([0, 5, 5]), f"2026-01-0{rng.randint(1, 3)}T00:00:00")
            for i in range(12)]
    # also a few exact duplicates apart from id
    pool += [c("zz1", "900", 20, 25, 5), c("zz2", "900", 20, 25, 5)]
    base = rank(pool, W, sort)
    for _ in range(25):
        shuffled = pool[:]
        rng.shuffle(shuffled)
        assert rank(shuffled, W, sort) == base
    assert rank(pool, W, sort) == base
    assert [r["rank"] for r in base] == list(range(1, len(pool) + 1))


@pytest.mark.parametrize("sort", SORTS)
def test_all_permutations_of_full_tie_sort_by_submission_then_id(sort):
    cs = [c("b", "100", 5, key="1"), c("a", "100", 5, key="1"), c("c", "100", 5, key="0"), c("d", "100", 5, key="2")]
    for perm in itertools.permutations(cs):
        assert ids(list(perm), sort) == ["c", "a", "b", "d"]


def test_tie_break_precedence_price_then_transit_then_created_then_id():
    # same score is forced by identical (amount, transit); only created/id differ
    assert ids([c("x", "50", 9, key="2"), c("y", "50", 9, key="1")]) == ["y", "x"]
    # equal amount, different transit under sort=price: shorter transit first
    assert ids([c("slow", "50", 9), c("fast", "50", 3)], "price") == ["fast", "slow"]
    # equal transit, different amount under sort=transit: cheaper first
    assert ids([c("dear", "60", 3), c("cheap", "50", 3)], "transit") == ["cheap", "dear"]
    # sort=price: equal amount and transit -> higher score first is moot (same), then created, then id
    assert ids([c("b", "50", 3, key="1"), c("a", "50", 3, key="1")], "price") == ["a", "b"]
    # sort=rating: equal shrunk rating -> cheaper, then faster, then earlier, then id
    assert ids([c("p", "90", 5, 25, 5), c("q", "80", 9, 25, 5), c("r", "80", 4, 25, 5)], "rating") == ["r", "q", "p"]


def test_score_rounding_tie_still_deterministic():
    # scores that round to the same 0.1 are ordered by the tie chain (cheaper first), never by input order
    a, b = c("a", "1000", 20), c("b", "1001", 20)
    assert ids([a, b]) == ids([b, a]) == ["a", "b"]


def test_ranking_is_exact_decimal_and_bounded():
    rows = rank([c("a", "333.33", 7, 13, 3), c("b", "999.99", 1), c("c", "1", 365, 500, 100)], W)
    for r in rows:
        assert isinstance(r["score"], Decimal) and Decimal(0) < r["score"] <= Decimal(100)
        assert all(isinstance(v["value"], Decimal) and 0 < v["value"] <= 1 for v in r["breakdown"].values())
    assert sorted(r["score"] for r in rows)[-1] == max(r["score"] for r in rows)


def test_weight_scaling_does_not_change_order():
    cs = [c("a", "100", 30), c("b", "120", 10, 20, 5), c("c", "90", 45, 5, 1)]
    assert ids(cs, "score", normalise_weights(50, 30, 20)) == ids(cs, "score", normalise_weights(5, 3, 2)) \
        == ids(cs, "score", normalise_weights(500, 300, 200))


def test_single_dimension_weights_follow_that_dimension():
    cs = [c("a", "100", 30), c("b", "120", 10, 25, 5), c("c", "90", 45)]
    assert ids(cs, "score", normalise_weights(1, 0, 0))[0] == "c"
    assert ids(cs, "score", normalise_weights(0, 1, 0))[0] == "b"
    assert ids(cs, "score", normalise_weights(0, 0, 1))[0] == "b"


def test_cheaper_quote_ids_sorted_and_badges_on_ties():
    rows = {r["quote_id"]: r for r in rank([c("b", "100", 5), c("a", "100", 5), c("z", "200", 9)], W)}
    assert rows["z"]["cheaper_quote_ids"] == ["a", "b"]
    assert "cheapest" in rows["a"]["badges"] and "cheapest" in rows["b"]["badges"]  # a tie shares the badge
