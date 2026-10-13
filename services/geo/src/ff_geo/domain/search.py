from .data import Dataset
from .geometry import haversine_km
from .models import City, Hub, NearestHub
from .text import normalize

HUB_TYPE_ALIASES = {"land": "land_border"}


def resolve_hub_type(t: str | None) -> str | None:
    return HUB_TYPE_ALIASES.get(t, t) if t else None


def search_cities(ds: Dataset, q: str | None = None, country: str | None = None) -> list[City]:
    items = [c for c in ds.cities if not country or c.country_code == country.upper()]
    if not q or not normalize(q):
        return sorted(items, key=lambda c: c.name_en)
    nq = normalize(q)
    scored: list[tuple[int, str, City]] = []
    for c in items:
        names = (normalize(c.name_en), normalize(c.name_ar))
        if any(n.startswith(nq) for n in names):
            scored.append((0, c.name_en, c))
        elif any(nq in n for n in names):
            scored.append((1, c.name_en, c))
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
