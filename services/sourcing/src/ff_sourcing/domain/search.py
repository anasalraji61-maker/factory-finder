"""Pure search logic: filtering, relevance, de-dup, ranking, pagination. No I/O."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from itertools import permutations

from .categories import _BY_SLUG, category_labels, expand_category
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
    sibling: bool = False  # a term matched only the secondary segment of a compound category label


# kind/condition are searchable like a category: "used production line" / "خط انتاج مستعمل"
_KIND_TEXT = {
    "production_line": "production line خط انتاج خطوط انتاج",
    "raw_material": "raw material مواد اوليه خام",
    "product": "product منتج",
}
_CONDITION_TEXT = {"used": "used مستعمل", "refurbished": "refurbished مجدد"}


_ARABIC_AND = "و"


def _primary_category_tokens(listing: Listing) -> tuple[str, ...]:
    """Tokens of the leading segment of the category label ("Pumps" of "Pumps & air conditioning"), plus kind/condition."""
    node = _BY_SLUG.get(listing.category or "")
    head_en = node.name.split("&")[0] if node else ""
    head_ar: list[str] = []
    for w in (node.name_ar if node else "").split():
        if head_ar and w.startswith(_ARABIC_AND):
            break
        head_ar.append(w)
    extra = f"{_KIND_TEXT.get(listing.kind, '')} {_CONDITION_TEXT.get(listing.condition, '')}"
    return tokens(f"{head_en} {' '.join(head_ar)} {listing.category or ''} {extra}".replace("_", " "))


def _doc_fields(listing: Listing) -> tuple[tuple[float, tuple[str, ...]], ...]:
    node_text = (
        f"{category_labels(listing.category)} {(listing.category or '').replace('_', ' ')} "
        f"{_KIND_TEXT.get(listing.kind, '')} {_CONDITION_TEXT.get(listing.condition, '')}"
    )
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


# Arabic words with an unrelated second sense: a hit on the bare word alone is down-weighted so the intended
# sense (flour; every other synonym of the group) wins. "دقيق" = flour / accurate ("High Precision" CNC).
AMBIGUOUS_FACTOR = 0.35
_AMBIGUOUS: frozenset[tuple[str, ...]] = frozenset({tokens("دقيق")})


@lru_cache(maxsize=4096)
def _split_alternatives(term: QueryTerm) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    return (
        tuple(a for a in term.alternatives if a not in _AMBIGUOUS),
        tuple(a for a in term.alternatives if a in _AMBIGUOUS),
    )


def _term_score(term: QueryTerm, fields) -> float:
    strong, weak = _split_alternatives(term)
    best = 0.0
    for weight, doc in fields:  # fields are ordered by weight: first exact hit is the best
        if any(contains_phrase(doc, alt) for alt in strong):
            best = weight
            break
    for weight, doc in fields:
        if weight * AMBIGUOUS_FACTOR <= best:
            break
        if any(contains_phrase(doc, alt) for alt in weak):
            return max(best, weight * AMBIGUOUS_FACTOR)
    if best:
        return best
    if term.fuzzy:
        for weight, doc in fields:
            if fuzzy_in(doc, term.fuzzy):
                return weight * FUZZY_FACTOR
    return 0.0


def _spans(term: QueryTerm, doc: tuple[str, ...]) -> list[tuple[int, int]]:
    out = []
    for alt in term.alternatives:
        n = len(alt)
        out += [(i, i + n) for i in range(len(doc) - n + 1) if doc[i : i + n] == alt]
    return out


def synonym_phrase(terms: list[QueryTerm], doc: tuple[str, ...]) -> bool:
    """All terms (any synonym) sit side by side in the title, in either order.

    Lets "مضخة ماء" boost "Water Pump" (Arabic noun-adjective order is the reverse of English).
    """
    if not 2 <= len(terms) <= 4:
        return False
    spans = [_spans(t, doc) for t in terms]
    if not all(spans):
        return False
    for order in permutations(range(len(terms))):
        frontier = {end for _, end in spans[order[0]]}
        for k in order[1:]:
            frontier = {end for start, end in spans[k] if start in frontier}
            if not frontier:
                break
        else:
            return True
    return False


def match(terms: list[QueryTerm], listing: Listing, phrase: tuple[str, ...] = ()) -> Match | None:
    """Field-weighted relevance; None when any query term is missing (AND semantics)."""
    if not terms:
        return Match(0.5)
    fields = _doc_fields(listing)
    total = 0.0
    sibling = False
    primary: tuple[str, ...] | None = None
    for term in terms:
        sc = _term_score(term, fields)
        if sc <= 0:
            return None
        total += sc
        if sc == F_CATEGORY:  # category-level hit: is it the category's own head word or a sibling segment?
            primary = _primary_category_tokens(listing) if primary is None else primary
            sibling = sibling or not any(contains_phrase(primary, alt) for alt in term.alternatives)
    exact_phrase = False
    if len(phrase) > 1:
        title_ar = tokens(listing.title_ar or "")
        title_en = tokens(listing.title)
        exact_phrase = contains_phrase(title_en, phrase) or contains_phrase(title_ar, phrase)
    if not exact_phrase and len(terms) > 1:
        exact_phrase = synonym_phrase(terms, tokens(listing.title)) or synonym_phrase(
            terms, tokens(listing.title_ar or "")
        )
    return Match(total / (F_TITLE * len(terms)), exact_phrase, sibling)


WEAK_RELEVANCE, STRONG_RELEVANCE, TITLE_RELEVANCE = 0.4, 0.6, 0.95


def prune_weak(items: list[tuple[Listing, Match]]) -> list[tuple[Listing, Match]]:
    """Drop supplier/city/description-only single-term hits (relevance < 0.4) when real title/category hits exist.

    "camera" must not return a charger just because its supplier is called "... Camera Co".
    With no strong hit at all the weak ones are kept (better than an empty page).
    """
    if not any(m.relevance >= STRONG_RELEVANCE for _, m in items):
        return items
    items = [it for it in items if it[1].relevance >= WEAK_RELEVANCE]
    # category-aware pruning: when real title hits exist, listings that only reach the query through a secondary
    # segment of a compound category label ("مكيف" -> pumps/generators in "Pumps & air conditioning") are siblings.
    if any(m.relevance >= TITLE_RELEVANCE for _, m in items):
        items = [it for it in items if not it[1].sibling]
    return items


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
    # inclusive; listings with unknown MOQ cannot be shown to satisfy a floor > 0
    if q.moq_min and (listing.moq is None or listing.moq < q.moq_min):
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
        if cur is None or (listing.price.min.amount, listing.source, listing.id) < (
            cur[0].price.min.amount,
            cur[0].source,
            cur[0].id,
        ):  # full tie-break: the survivor must not depend on adapter completion order
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
    first_rank: dict[str | None, dict[Decimal, int]] = {}
    for cat, v in groups.items():
        v.sort()
        pos: dict[Decimal, int] = {}
        for i, p in enumerate(v):
            pos.setdefault(p, i)  # list.index semantics: first position among equal prices
        first_rank[cat] = pos

    def price_fit(listing: Listing) -> float:
        prices = groups[listing.category]
        if len(prices) < 2:
            return 0.5
        return 1.0 - first_rank[listing.category][mid_price(listing)] / (len(prices) - 1)

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
    if page < 1 or page_size < 1:  # negative slice indexes would silently wrap around and leak items
        return []
    start = (page - 1) * page_size
    return items[start : start + page_size]
