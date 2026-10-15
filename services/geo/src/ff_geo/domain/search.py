from .data import Dataset
from .geometry import haversine_km
from .models import City, Hub, NearestHub
from .text import normalize

HUB_TYPE_ALIASES = {"land": "land_border"}


def resolve_hub_type(t: str | None) -> str | None:
    return HUB_TYPE_ALIASES.get(t, t) if t else None


_NORM_CACHE: dict[int, tuple[Dataset, dict[str, tuple[str, ...]]]] = {}
_MIN_SUBSTRING = 3  # shorter queries only match at the start of a name/word (avoids noise from "la", "al")
_MIN_FUZZY = 4  # typo tolerance only for queries of at least this length


def _strip_al(s: str) -> str:
    """Drop the Arabic definite article from each word (الحلة -> حله) so queries match with or without it."""
    return " ".join(w[2:] if w.startswith("ال") and len(w) > 3 else w for w in s.split())


def _variants(s: str) -> tuple[str, ...]:
    n = normalize(s)
    d = _strip_al(n)
    return (n,) if d == n else (n, d)


def _city_names(ds: Dataset) -> dict[str, tuple[str, ...]]:
    """Normalised searchable names (en, ar, aliases) per city id, computed once per dataset."""
    hit = _NORM_CACHE.get(id(ds))
    if hit is None or hit[0] is not ds:
        _NORM_CACHE.clear()  # at most one dataset is live; keeps this bounded
        table: dict[str, tuple[str, ...]] = {}
        for c in ds.cities:
            raw = [c.name_en, c.name_ar, *ds.aliases.get(c.id, [])]
            seen: dict[str, None] = {}
            for r in raw:
                for v in _variants(r):
                    if v:
                        seen[v] = None
            table[c.id] = tuple(seen)
        hit = (ds, table)
        _NORM_CACHE[id(ds)] = hit
    return hit[1]


def _osa(a: str, b: str, limit: int) -> int:
    """Optimal-string-alignment edit distance (adjacent swap = 1); returns limit+1 once it must exceed limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def _match_rank(qs: tuple[str, ...], names: tuple[str, ...]) -> int | None:
    """0 exact, 1 name prefix, 2 word prefix, 3 substring; None if no direct match."""
    best: int | None = None
    for q in qs:
        for n in names:
            if n == q:
                return 0
            if n.startswith(q):
                r = 1
            elif any(w.startswith(q) for w in n.split()):
                r = 2
            elif len(q) >= _MIN_SUBSTRING and q in n:
                r = 3
            else:
                continue
            if best is None or r < best:
                best = r
    return best


def _fuzzy_distance(qs: tuple[str, ...], names: tuple[str, ...]) -> int | None:
    best: int | None = None
    for q in qs:
        if len(q) < _MIN_FUZZY:
            continue
        limit = 1 if len(q) <= 6 else 2
        for n in names:
            # whole name, typo'd prefix of a longer name, or any single word of it
            cands = {n, n[: len(q)], *n.split()}
            for cand in cands:
                d = _osa(q, cand, limit)
                if d <= limit and (best is None or d < best):
                    best = d
    return best


def search_cities(ds: Dataset, q: str | None = None, country: str | None = None) -> list[City]:
    """Rank by exact > prefix > word-prefix > substring over en/ar names and aliases; if nothing matches,
    fall back to typo-tolerant matching (edit distance <= 1-2). Arabic is normalised (alef/ya/ta-marbuta, ال)."""
    items = [c for c in ds.cities if not country or c.country_code == country.upper()]
    if not q or not normalize(q):
        return sorted(items, key=lambda c: c.name_en)
    qs = _variants(q)
    norm = _city_names(ds)
    scored: list[tuple[int, str, City]] = []
    for c in items:
        r = _match_rank(qs, norm[c.id])
        if r is not None:
            scored.append((r, c.name_en, c))
    if not scored:
        for c in items:
            d = _fuzzy_distance(qs, norm[c.id])
            if d is not None:
                scored.append((d, c.name_en, c))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [c for _, _, c in scored]


def filter_hubs(ds: Dataset, country: str | None = None, type_: str | None = None) -> list[Hub]:
    t = resolve_hub_type(type_)
    cc = country.upper() if country else None
    return [
        h
        for h in ds.hubs
        if (not t or h.type == t) and (not cc or h.country_code == cc or cc in h.serves_countries)
    ]


def nearest_hubs(
    ds: Dataset,
    lat: float,
    lon: float,
    type_: str | None = None,
    limit: int = 3,
    country: str | None = None,
) -> list[NearestHub]:
    cands = filter_hubs(ds, country, type_)
    ranked = sorted(
        ((haversine_km(lat, lon, h.point.lat, h.point.lon), h) for h in cands), key=lambda t: t[0]
    )
    return [NearestHub(**h.model_dump(), distance_km=round(d, 1)) for d, h in ranked[:limit]]
