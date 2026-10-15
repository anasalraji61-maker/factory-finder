"""Client for the geo service: Protocol + httpx implementation + deterministic mock."""
import asyncio
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True)
class Hub:
    id: str
    name: str
    type: str  # sea | air | land
    country_code: str
    lat: float
    lon: float

    @property
    def point(self) -> Point:
        return Point(self.lat, self.lon)


class GeoClient(Protocol):
    async def resolve_city(self, country_code: str, city: str | None) -> Point | None: ...
    async def hubs(self, country_code: str, type: str | None = None) -> list[Hub]: ...
    async def nearest_hubs(self, point: Point, type: str, limit: int = 2,
                           country_code: str | None = None) -> list[Hub]: ...
    async def distance_km(self, a: Point, b: Point, mode: str = "road") -> Decimal: ...


def haversine_km(a: Point, b: Point) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lon - a.lon)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- mock
CITIES = {  # (country, lowercase name) -> (lat, lon)
    ("CN", "shanghai"): (31.23, 121.47), ("CN", "yiwu"): (29.31, 120.08),
    ("CN", "guangzhou"): (23.13, 113.26), ("CN", "ningbo"): (29.87, 121.55),
    ("CN", "shenzhen"): (22.54, 114.06), ("CN", "urumqi"): (43.83, 87.62),
    ("IQ", "baghdad"): (33.31, 44.37), ("IQ", "erbil"): (36.19, 44.01),
    ("IQ", "basra"): (30.51, 47.78), ("IQ", "najaf"): (32.03, 44.34),
    ("IQ", "mosul"): (36.34, 43.13),
    ("DE", "hamburg"): (53.55, 9.99), ("DE", "berlin"): (52.52, 13.40),
    ("TR", "istanbul"): (41.01, 28.98), ("TR", "mersin"): (36.80, 34.64),
    ("AE", "dubai"): (25.20, 55.27), ("US", "los angeles"): (34.05, -118.24),
    ("US", "new york"): (40.71, -74.01), ("IR", "tehran"): (35.69, 51.39),
    ("SA", "riyadh"): (24.71, 46.68), ("EG", "cairo"): (30.04, 31.24),
    ("IN", "mumbai"): (19.08, 72.88), ("JO", "amman"): (31.95, 35.93),
    ("GH", "accra"): (5.60, -0.19), ("PE", "lima"): (-12.05, -77.04), ("MX", "mexico city"): (19.43, -99.13),
    ("LK", "colombo"): (6.93, 79.85), ("SE", "stockholm"): (59.33, 18.07), ("GR", "athens"): (37.98, 23.73),
    ("CH", "zurich"): (47.37, 8.54), ("KZ", "almaty"): (43.24, 76.89),
}
HUBS = [  # id, name, type, country, lat, lon
    ("CNSHA", "Shanghai", "sea", "CN", 31.23, 121.47), ("CNNGB", "Ningbo-Zhoushan", "sea", "CN", 29.87, 121.85),
    ("CNYTN", "Yantian (Shenzhen)", "sea", "CN", 22.57, 114.28), ("CNCAN", "Nansha (Guangzhou)", "sea", "CN", 22.75, 113.6),
    ("PVG", "Shanghai Pudong", "air", "CN", 31.14, 121.81), ("CAN", "Guangzhou Baiyun", "air", "CN", 23.39, 113.30),
    ("CNALA", "Alashankou rail", "land", "CN", 45.17, 82.57),
    ("IQUQR", "Umm Qasr", "sea", "IQ", 30.03, 47.93), ("BGW", "Baghdad Intl", "air", "IQ", 33.26, 44.23),
    ("EBL", "Erbil Intl", "air", "IQ", 36.24, 43.96), ("BSR", "Basra Intl", "air", "IQ", 30.55, 47.66),
    ("IQIBK", "Ibrahim Khalil", "land", "IQ", 37.08, 42.38), ("IQSAF", "Safwan", "land", "IQ", 30.10, 47.70),
    ("TRMER", "Mersin", "sea", "TR", 36.78, 34.63), ("TRIST", "Ambarli (Istanbul)", "sea", "TR", 40.97, 28.69),
    ("IST", "Istanbul Airport", "air", "TR", 41.26, 28.74),
    ("AEJEA", "Jebel Ali", "sea", "AE", 25.01, 55.06), ("DXB", "Dubai Intl", "air", "AE", 25.25, 55.36),
    ("DEHAM", "Hamburg", "sea", "DE", 53.54, 9.97), ("HAM", "Hamburg Airport", "air", "DE", 53.63, 9.99),
    ("FRA", "Frankfurt", "air", "DE", 50.03, 8.57),
    ("USLAX", "Los Angeles", "sea", "US", 33.74, -118.27), ("USNYC", "New York/NJ", "sea", "US", 40.67, -74.04),
    ("LAX", "Los Angeles Intl", "air", "US", 33.94, -118.41), ("JFK", "New York JFK", "air", "US", 40.64, -73.78),
    ("IRBND", "Bandar Abbas", "sea", "IR", 27.1, 56.07), ("IKA", "Tehran IKA", "air", "IR", 35.42, 51.15),
    ("SAJED", "Jeddah", "sea", "SA", 21.48, 39.17), ("RUH", "Riyadh KKIA", "air", "SA", 24.96, 46.70),
    ("EGALY", "Alexandria", "sea", "EG", 31.19, 29.88), ("CAI", "Cairo Intl", "air", "EG", 30.12, 31.41),
    ("INNSA", "Nhava Sheva", "sea", "IN", 18.95, 72.95), ("BOM", "Mumbai Intl", "air", "IN", 19.09, 72.87),
    ("JOAQJ", "Aqaba", "sea", "JO", 29.52, 35.0), ("AMM", "Amman Queen Alia", "air", "JO", 31.72, 35.99),
    ("GHTEM", "Tema", "sea", "GH", 5.63, 0.02), ("ACC", "Accra Kotoka", "air", "GH", 5.61, -0.17),
    ("PECLL", "Callao", "sea", "PE", -12.05, -77.15), ("LIM", "Lima Jorge Chavez", "air", "PE", -12.02, -77.11),
    ("MXZLO", "Manzanillo", "sea", "MX", 19.05, -104.31), ("MEX", "Mexico City Intl", "air", "MX", 19.44, -99.07),
    ("LKCMB", "Colombo", "sea", "LK", 6.95, 79.85), ("CMB", "Colombo Bandaranaike", "air", "LK", 7.18, 79.88),
    ("SEGOT", "Gothenburg", "sea", "SE", 57.70, 11.93), ("ARN", "Stockholm Arlanda", "air", "SE", 59.65, 17.92),
    ("GRPIR", "Piraeus", "sea", "GR", 37.94, 23.64), ("ATH", "Athens Intl", "air", "GR", 37.94, 23.94),
    ("ZRH", "Zurich Airport", "air", "CH", 47.46, 8.55), ("ALA", "Almaty Airport", "air", "KZ", 43.35, 77.04),
]
ROAD_FACTOR = {"road": 1.3, "sea": 1.25, "air": 1.0}


class MockGeo:
    """Deterministic in-memory geo (haversine x factor). Default in tests."""

    def __init__(self):
        self._hubs = [Hub(*h) for h in HUBS]

    async def resolve_city(self, country_code, city):
        if city:
            hit = CITIES.get((country_code, city.strip().lower()))
            return Point(*hit) if hit else None
        for (cc, _), ll in CITIES.items():
            if cc == country_code:
                return Point(*ll)
        return None

    async def hubs(self, country_code, type=None):
        return [h for h in self._hubs if h.country_code == country_code and type in (None, h.type)]

    async def nearest_hubs(self, point, type, limit=2, country_code=None):
        pool = [h for h in self._hubs if h.type == type and country_code in (None, h.country_code)]
        return sorted(pool, key=lambda h: haversine_km(point, h.point))[:limit]

    async def distance_km(self, a, b, mode="road"):
        return Decimal(str(round(haversine_km(a, b) * ROAD_FACTOR.get(mode, 1.3), 1)))


# ---------------------------------------------------------------- http
def _items(data) -> list[dict]:
    return data if isinstance(data, list) else data.get("items", [])


def _pt(d: dict) -> Point | None:
    p = d.get("point") or d
    lat, lon = p.get("lat", p.get("latitude")), p.get("lon", p.get("lng", p.get("longitude")))
    return Point(float(lat), float(lon)) if lat is not None and lon is not None else None


def _hub(d: dict) -> Hub | None:
    p = _pt(d)
    if p is None:
        return None
    return Hub(str(d.get("id") or d.get("code")), d.get("name_en") or d.get("name", ""), d.get("type", ""),
               d.get("country_code") or d.get("country", ""), p.lat, p.lon)


class HttpGeo:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self.base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=5)

    async def _get(self, path: str, **params):
        r = await self._client.get(self.base + path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    async def resolve_city(self, country_code, city):
        items = _items(await self._get("/v1/cities", country=country_code, q=city))
        for it in items:
            if p := _pt(it):
                return p
        return None

    async def hubs(self, country_code, type=None):
        return [h for it in _items(await self._get("/v1/hubs", country=country_code, type=type))
                if (h := _hub(it))]

    async def nearest_hubs(self, point, type, limit=2, country_code=None):
        data = await self._get("/v1/hubs/nearest", lat=point.lat, lon=point.lon, type=type,
                               limit=limit * 3 if country_code else limit)
        hubs = [h for it in _items(data) if (h := _hub(it))]
        if country_code:
            hubs = [h for h in hubs if h.country_code == country_code]
        return hubs[:limit]

    async def distance_km(self, a, b, mode="road"):
        d = await self._get("/v1/distance", from_lat=a.lat, from_lon=a.lon, to_lat=b.lat,
                            to_lon=b.lon, mode=mode)
        return Decimal(str(d.get("distance_km", d.get("km"))))


# ---------------------------------------------------------------- cache
class CachedGeo:
    """TTL + size bounded memoisation in front of any GeoClient.

    Geo data (cities, hubs, distances) is static reference data and a landed-cost quote repeats the
    same lookups dozens of times (once per mode x hub pair), each a network hop with the http client.
    Errors are never cached. Results are returned as-is (hubs lists are copied so callers may mutate).
    """

    def __init__(self, inner: GeoClient, ttl_s: float = 600.0, max_entries: int = 4096, clock=None):
        import time
        self.inner, self.ttl_s, self.max_entries = inner, ttl_s, max_entries
        self._now = clock or time.monotonic
        self._data: dict = {}
        self._inflight: dict = {}  # key -> shared task; removed on completion so bounded by concurrency
        self.hits = self.misses = self.shared = 0

    @property
    def _client(self):  # lets the app lifespan close the wrapped httpx client
        return getattr(self.inner, "_client", None)

    async def _cached(self, key, call):
        hit = self._data.get(key)
        now = self._now()
        if hit is not None and hit[0] > now:
            self.hits += 1
            return hit[1]
        task = self._inflight.get(key)
        if task is not None:
            self.shared += 1
            return await asyncio.shield(task)  # one waiter cancelling must not cancel the others
        self.misses += 1
        if len(self._inflight) >= self.max_entries:  # bound the in-flight table: skip sharing
            return await self._fill(key, call)
        task = asyncio.ensure_future(self._fill(key, call))
        self._inflight[key] = task

        def _done(t, key=key):
            if self._inflight.get(key) is t:
                del self._inflight[key]
            if not t.cancelled():
                t.exception()  # mark retrieved (no "never retrieved" noise if every waiter left)

        task.add_done_callback(_done)
        return await asyncio.shield(task)

    async def _fill(self, key, call):
        value = await call()  # errors propagate to every sharer and are never cached
        now = self._now()
        if len(self._data) >= self.max_entries:
            for k in [k for k, (exp, _) in self._data.items() if exp <= now] or [next(iter(self._data))]:
                self._data.pop(k, None)
        self._data[key] = (now + self.ttl_s, value)
        return value

    async def resolve_city(self, country_code, city):
        return await self._cached(("city", country_code, city), lambda: self.inner.resolve_city(country_code, city))

    async def hubs(self, country_code, type=None):
        return list(await self._cached(("hubs", country_code, type), lambda: self.inner.hubs(country_code, type)))

    async def nearest_hubs(self, point, type, limit=2, country_code=None):
        return list(await self._cached(("near", point, type, limit, country_code),
                                       lambda: self.inner.nearest_hubs(point, type, limit, country_code)))

    async def distance_km(self, a, b, mode="road"):
        return await self._cached(("dist", a, b, mode), lambda: self.inner.distance_km(a, b, mode))
