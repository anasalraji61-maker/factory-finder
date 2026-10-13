"""Pure search logic: filtering, relevance, de-dup, ranking, pagination. No I/O."""

from __future__ import annotations

from decimal import Decimal

from .categories import category_labels, expand_category
from .models import Listing, SearchQuery
from .text import QueryTerm, contains_phrase, tokens

TRUST_VALUE = {"green": 1.0, "yellow": 0.6, "unknown": 0.35, "red": 0.0}
W_RELEVANCE, W_TRUST, W_PRICE = 0.55, 0.25, 0.20


def _doc_tokens(listing: Listing) -> tuple[list[str], list[str]]:
    primary = tokens(f"{listing.title} {listing.title_ar or ''}")
    secondary = tokens(
        f"{category_labels(listing.category)} {listing.supplier.name} "
        f"{listing.supplier.name_ar or ''} {(listing.origin.city if listing.origin else '') or ''}"
    )
    return primary, secondary


def relevance(terms: list[QueryTerm], listing: Listing) -> float | None:
    """0..1, or None when any query term is missing (AND semantics). No terms -> 0.5."""
    if not terms:
        return 0.5
    primary, secondary = _doc_tokens(listing)
    total = 0
    for term in terms:
        if any(contains_phrase(primary, alt) for alt in term.alternatives):
            total += 3
        elif any(contains_phrase(secondary, alt) for alt in term.alternatives):
            total += 1
        else:
            return None
    return total / (3 * len(terms))


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


def dedupe(items: list[tuple[Listing, float]]) -> list[tuple[Listing, float]]:
    """Same (source,id) or same supplier+normalized title collapses to the cheaper entry."""
    best: dict[tuple, tuple[Listing, float]] = {}
    for listing, rel in items:
        key = (listing.supplier.id, " ".join(tokens(listing.title)))
        cur = best.get(key)
        if cur is None or listing.price.min.amount < cur[0].price.min.amount:
            best[key] = (listing, rel)
    seen: set[tuple[str, str]] = set()
    out = []
    for item in best.values():
        k = (item[0].source, item[0].id)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def rank(items: list[tuple[Listing, float]]) -> list[Listing]:
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

    def score(item: tuple[Listing, float]) -> tuple[float, str]:
        listing, rel = item
        s = (
            W_RELEVANCE * rel
            + W_TRUST * TRUST_VALUE[listing.supplier.trust_band]
            + W_PRICE * price_fit(listing)
        )
        return (-s, listing.id)

    return [listing for listing, _ in sorted(items, key=score)]


def paginate[T](items: list[T], page: int, page_size: int) -> list[T]:
    start = (page - 1) * page_size
    return items[start : start + page_size]
