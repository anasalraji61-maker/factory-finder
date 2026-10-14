"""Pure search logic: filtering, relevance, de-dup, ranking, pagination. No I/O."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from .categories import category_labels, expand_category
from .models import Listing, SearchQuery
from .text import QueryTerm, contains_phrase, fuzzy_in, tokens

TRUST_VALUE = {"green": 1.0, "yellow": 0.6, "unknown": 0.35, "red": 0.0}
# relevance dominates; phrase/trust/verified/price are tie-shapers
W_RELEVANCE, W_PHRASE, W_TRUST, W_VERIFIED, W_PRICE = 0.62, 0.10, 0.12, 0.03, 0.13
# field weights: title > category > description > supplier/city
F_TITLE, F_CATEGORY, F_DESCRIPTION, F_SUPPLIER = 1.0, 0.6, 0.35, 0.2
FUZZY_FACTOR = 0.8  # a typo-tolerant hit counts a bit less than an exact one
SORTS = ("relevance", "price_asc", "price_desc", "trust", "moq")


@dataclass(frozen=True)
class Match:
    relevance: float  # 0..1
    phrase: bool = False  # whole query appears contiguously in the title


def _doc_fields(listing: Listing) -> tuple[tuple[float, tuple[str, ...]], ...]:
    node_text = f"{category_labels(listing.category)} {(listing.category or '').replace('_', ' ')}"
    desc = f"{getattr(listing, 'description', None) or ''} {getattr(listing, 'description_ar', None) or ''}"
    return (
        (F_TITLE, tokens(f"{listing.title} {listing.title_ar or ''}")),
        (F_CATEGORY, tokens(node_text)),
        (F_DESCRIPTION, tokens(desc)),
        (
            F_SUPPLIER,
            tokens(
                f"{listing.supplier.name} {listing.supplier.name_ar or ''} "
                f"{(listing.origin.city if listing.origin else '') or ''}"
            ),
        ),
    )


def _term_score(term: QueryTerm, fields) -> float:
    for weight, doc in fields:  # fields are ordered by weight: first exact hit is the best
        if any(contains_phrase(doc, alt) for alt in term.alternatives):
            return weight
    if term.fuzzy:
        for weight, doc in fields:
            if fuzzy_in(doc, term.fuzzy):
                return weight * FUZZY_FACTOR
    return 0.0


def match(terms: list[QueryTerm], listing: Listing, phrase: tuple[str, ...] = ()) -> Match | None:
    """Field-weighted relevance; None when any query term is missing (AND semantics)."""
    if not terms:
        return Match(0.5)
    fields = _doc_fields(listing)
    total = 0.0
    for term in terms:
        sc = _term_score(term, fields)
        if sc <= 0:
            return None
        total += sc
    exact_phrase = False
    if len(phrase) > 1:
        title_ar = tokens(listing.title_ar or "")
        title_en = tokens(listing.title)
        exact_phrase = contains_phrase(title_en, phrase) or contains_phrase(title_ar, phrase)
    return Match(total / (F_TITLE * len(terms)), exact_phrase)


def relevance(terms: list[QueryTerm], listing: Listing) -> float | None:
    m = match(terms, listing)
    return None if m is None else m.relevance


def mid_price(listing: Listing) -> Decimal:
    return (listing.price.min.amount + listing.price.max.amount) / 2


def passes_filters(listing: Listing, q: SearchQuery) -> bool:
    if q.kind and listing.kind != q.kind:
        return False
    if q.condition != "any" and listing.condition != q.condition:
        return False
    country = (listing.origin or listing.supplier.location).country_code
    if q.origin_country and country != q.origin_country.upper():
        return False
    if q.category and listing.category not in expand_category(q.category):
        return False
    if listing.price.min.currency == "USD":  # only USD comparable without FX; see decisions
        if q.min_price is not None and listing.price.max.amount < q.min_price:
            return False
        if q.max_price is not None and listing.price.min.amount > q.max_price:
            return False
    if q.moq_max is not None and listing.moq is not None and listing.moq > q.moq_max:
        return False
    return not (q.verified_only and not listing.supplier.verified)


def dedupe(items: list[tuple[Listing, Match]]) -> list[tuple[Listing, Match]]:
    """Same (source,id) or same supplier+normalized title collapses to the cheaper entry."""
    best: dict[tuple, tuple[Listing, Match]] = {}
    for listing, m in items:
        key = (listing.supplier.id, " ".join(tokens(listing.title)))
        if listing.source == "native":  # a supplier's own distinct listings are never merged
            key = (*key, listing.id)
        cur = best.get(key)
        if cur is None or listing.price.min.amount < cur[0].price.min.amount:
            best[key] = (listing, m)
    seen: set[tuple[str, str]] = set()
    out = []
    for item in best.values():
        k = (item[0].source, item[0].id)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def _price_key(listing: Listing) -> tuple[int, Decimal]:
    # USD first: other currencies are not comparable without FX, so they sort after
    return (0 if listing.price.min.currency == "USD" else 1, mid_price(listing))


def rank(items: list[tuple[Listing, Match]], sort: str = "relevance") -> list[Listing]:
    groups: dict[str | None, list[Decimal]] = {}
    for listing, _ in items:
        groups.setdefault(listing.category, []).append(mid_price(listing))
    for v in groups.values():
        v.sort()

    def price_fit(listing: Listing) -> float:
        prices = groups[listing.category]
        if len(prices) < 2:
            return 0.5
        return 1.0 - prices.index(mid_price(listing)) / (len(prices) - 1)

    def relevance_score(item: tuple[Listing, Match]) -> float:
        listing, m = item
        return (
            W_RELEVANCE * m.relevance
            + W_PHRASE * (1.0 if m.phrase else 0.0)
            + W_TRUST * TRUST_VALUE[listing.supplier.trust_band]
            + W_VERIFIED * (1.0 if listing.supplier.verified else 0.0)
            + W_PRICE * price_fit(listing)
        )

    scores = {item[0].id: relevance_score(item) for item in items}

    def key(item: tuple[Listing, Match]):
        listing = item[0]
        tie = (-scores[listing.id], listing.id)  # stable: score desc, then id
        if sort == "price_asc":
            return (_price_key(listing), *tie)
        if sort == "price_desc":
            cur, amt = _price_key(listing)
            return (cur, -amt, *tie)
        if sort == "trust":
            ts = listing.supplier.trust_score
            return (-(ts if ts is not None else -1), -TRUST_VALUE[listing.supplier.trust_band], *tie)
        if sort == "moq":
            return (listing.moq is None, listing.moq or 0, *tie)
        return tie

    return [listing for listing, _ in sorted(items, key=key)]


def facets(listings: list[Listing]) -> dict[str, list[dict]]:
    """Counts by kind / condition / origin_country / category over the whole matched set."""
    counters: dict[str, Counter] = {
        "kind": Counter(),
        "condition": Counter(),
        "origin_country": Counter(),
        "category": Counter(),
    }
    for item in listings:
        counters["kind"][item.kind] += 1
        counters["condition"][item.condition] += 1
        counters["origin_country"][(item.origin or item.supplier.location).country_code] += 1
        if item.category:
            counters["category"][item.category] += 1
    return {
        name: [{"value": v, "count": n} for v, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]
        for name, c in counters.items()
    }


def paginate[T](items: list[T], page: int, page_size: int) -> list[T]:
    start = (page - 1) * page_size
    return items[start : start + page_size]
