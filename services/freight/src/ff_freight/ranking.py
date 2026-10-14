"""Explainable quote ranking (pure, deterministic, Decimal arithmetic).

For each comparable quote (same currency as the request, not expired, visible, forwarder active):

* price_score    = cheapest_amount / amount                    (1.0 for the cheapest)
* transit_score  = fastest_transit_days / transit_days         (1.0 for the fastest)
* rating_score   = ((rating_sum + PRIOR_STARS * PRIOR_WEIGHT) / (rating_count + PRIOR_WEIGHT)) / 5

The rating is shrunk toward a neutral prior (3.0 stars worth 2 ratings), so a forwarder without
ratings scores 0.600 and a single 5-star rating cannot dominate. ``score`` is
100 * (w_price * price_score + w_transit * transit_score + w_rating * rating_score) with weights
normalised to sum to 1. Ties are broken by lower price, shorter transit, earlier submission, id.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PRIOR_STARS = Decimal(3)
PRIOR_WEIGHT = Decimal(2)
Q3 = Decimal("0.001")
Q1 = Decimal("0.1")


@dataclass(frozen=True)
class Candidate:
    quote_id: str
    amount: Decimal
    transit_days: int
    rating_sum: int
    rating_count: int
    created_key: str  # sortable submission key (iso time)


def shrunk_rating(rating_sum: int, rating_count: int) -> Decimal:
    return (Decimal(rating_sum) + PRIOR_STARS * PRIOR_WEIGHT) / (Decimal(rating_count) + PRIOR_WEIGHT)


def normalise_weights(wp: int, wt: int, wr: int) -> tuple[Decimal, Decimal, Decimal]:
    total = wp + wt + wr
    if total <= 0:
        wp, wt, wr, total = 50, 30, 20, 100
    d = Decimal(total)
    return Decimal(wp) / d, Decimal(wt) / d, Decimal(wr) / d


def rank(cands: list[Candidate], weights: tuple[Decimal, Decimal, Decimal], sort: str = "score") -> list[dict]:
    """Returns one dict per candidate in the requested order with rank, score and breakdown."""
    if not cands:
        return []
    wp, wt, wr = weights
    cheapest = min(c.amount for c in cands)
    fastest = min(c.transit_days for c in cands)
    best_rating = max(shrunk_rating(c.rating_sum, c.rating_count) for c in cands)
    rows = []
    for c in cands:
        ps = cheapest / c.amount
        ts = Decimal(fastest) / Decimal(c.transit_days)
        sr = shrunk_rating(c.rating_sum, c.rating_count)
        rs = sr / 5
        score = (Decimal(100) * (wp * ps + wt * ts + wr * rs)).quantize(Q1, ROUND_HALF_UP)
        rows.append(
            {
                "quote_id": c.quote_id,
                "score": score,
                "breakdown": {
                    "price": {"value": ps.quantize(Q3, ROUND_HALF_UP), "weight": wp.quantize(Q3, ROUND_HALF_UP)},
                    "transit": {"value": ts.quantize(Q3, ROUND_HALF_UP), "weight": wt.quantize(Q3, ROUND_HALF_UP)},
                    "rating": {"value": rs.quantize(Q3, ROUND_HALF_UP), "weight": wr.quantize(Q3, ROUND_HALF_UP)},
                },
                "adjusted_rating": sr.quantize(Decimal("0.01"), ROUND_HALF_UP),
                "badges": [
                    b
                    for b, on in (
                        ("cheapest", c.amount == cheapest),
                        ("fastest", c.transit_days == fastest),
                        ("top_rated", sr == best_rating and c.rating_count > 0),
                    )
                    if on
                ],
                "_c": c,
                "_sr": sr,
            }
        )
    tie = lambda r: (r["_c"].amount, r["_c"].transit_days, r["_c"].created_key, r["_c"].quote_id)  # noqa: E731
    if sort == "price":
        rows.sort(key=lambda r: (r["_c"].amount, r["_c"].transit_days, -r["score"], *tie(r)[2:]))
    elif sort == "transit":
        rows.sort(key=lambda r: (r["_c"].transit_days, r["_c"].amount, -r["score"], *tie(r)[2:]))
    elif sort == "rating":
        rows.sort(key=lambda r: (-r["_sr"], r["_c"].amount, *tie(r)[1:]))
    else:
        rows.sort(key=lambda r: (-r["score"], *tie(r)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["explanation"] = _explain(r, cheapest, fastest)
        del r["_c"], r["_sr"]
    return rows


def _explain(r: dict, cheapest: Decimal, fastest: int) -> list[str]:
    b = r["breakdown"]
    pct = lambda x: f"{(x * 100).quantize(Decimal('1'), ROUND_HALF_UP)}%"  # noqa: E731
    out = [
        f"price {pct(b['price']['value'])} of best (weight {pct(b['price']['weight'])})",
        f"transit {pct(b['transit']['value'])} of best (weight {pct(b['transit']['weight'])})",
        f"rating {r['adjusted_rating']}/5 after shrinking toward 3.0 (weight {pct(b['rating']['weight'])})",
    ]
    if r["badges"]:
        out.append("best " + ", ".join(r["badges"]).replace("_", " "))
    return out
