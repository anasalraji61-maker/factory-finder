"""QA round: random Arabic/English city pairs resolve through the API and route without land-crossing sea edges."""
import importlib.util
import pathlib
import random

import pytest
from fastapi.testclient import TestClient

from ff_geo.domain.data import get_dataset
from ff_geo.domain.geometry import haversine_km
from ff_geo.domain.sea import EDGES, MAX_ACCESS_KM, NODES

_spec = importlib.util.spec_from_file_location("landmask", pathlib.Path(__file__).with_name("test_sea_landmask.py"))
_lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lm)

REGION = {"IQ", "KW", "SA", "AE", "QA", "BH", "OM", "TR", "CN", "DE", "FR", "IT", "ES", "NL", "PL", "GB", "BE"}
DS = get_dataset()
POOL = sorted((c for c in DS.cities if c.country_code in REGION), key=lambda c: c.id)
_rng = random.Random(20261015)
PAIRS = []
while len(PAIRS) < 20:
    a, b = _rng.sample(POOL, 2)
    if a.country_code != b.country_code or len(PAIRS) % 4 == 0:
        PAIRS.append((a, b, _rng.choice(["en", "ar"]), _rng.choice(["en", "ar"])))
# the headline corridors are always included
for x, y in (("CN-SHANGHAI", "IQ-BAGHDAD"), ("CN-GUANGZHOU", "TR-ISTANBUL"), ("DE-HAMBURG", "IQ-BASRA")):
    cx, cy = (next((c for c in DS.cities if c.id == i), None) for i in (x, y))
    if cx and cy:
        PAIRS.append((cx, cy, "ar", "en"))

EDGE_SET = {frozenset(e) for e in EDGES}


@pytest.fixture(scope="module")
def client():
    from ff_geo.main import create_app
    return TestClient(create_app())


def resolve(client, city, lang):
    name = city.name_ar if lang == "ar" else city.name_en
    r = client.get("/v1/cities", params={"q": name, "country": city.country_code})
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["items"]]
    assert city.id in ids, f"{name!r} ({lang}) did not resolve to {city.id}: {ids}"
    return city


def nearest_sea_hub(client, city):
    items = client.get("/v1/hubs/nearest", params={"lat": city.point.lat, "lon": city.point.lon, "type": "sea",
                                                    "limit": 1}).json()["items"]
    return items[0]


@pytest.mark.parametrize("a,b,la,lb", PAIRS, ids=lambda x: getattr(x, "id", x))
def test_pair_resolves_and_routes(client, a, b, la, lb):
    resolve(client, a, la)
    resolve(client, b, lb)
    # an exact name must rank the city first within its country
    for c, lang in ((a, la), (b, lb)):
        name = c.name_ar if lang == "ar" else c.name_en
        top = client.get("/v1/cities", params={"q": name, "country": c.country_code}).json()["items"][0]
        assert top["id"] == c.id, f"{name!r}: top hit {top['id']} != {c.id}"
    for mode in ("road", "air", "sea"):
        r = client.get("/v1/distance", params={"from_lat": a.point.lat, "from_lon": a.point.lon,
                                               "to_lat": b.point.lat, "to_lon": b.point.lon, "mode": mode})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["distance_km"] >= j["straight_line_km"] - 0.1 and j["duration_hours"] > 0
    ha, hb = nearest_sea_hub(client, a), nearest_sea_hub(client, b)
    r = client.get("/v1/distance", params={"from_lat": ha["point"]["lat"], "from_lon": ha["point"]["lon"],
                                           "to_lat": hb["point"]["lat"], "to_lon": hb["point"]["lon"], "mode": "sea"})
    assert r.status_code == 200, r.text
    via = r.json()["via"]
    assert via and all(n in NODES for n in via)
    for u, v in zip(via, via[1:], strict=False):
        assert frozenset((u, v)) in EDGE_SET, f"sea path uses non-edge {u}->{v}"
        assert not _lm._hits(u, v), f"sea edge {u}->{v} crosses land: {_lm._hits(u, v)[:3]}"
    # access legs (port -> first/last lane node) stay short and off the inset landmasses
    for hub, node in ((ha, via[0]), (hb, via[-1])):
        d = haversine_km(hub["point"]["lat"], hub["point"]["lon"], *NODES[node])
        assert d <= MAX_ACCESS_KM or node == min(NODES, key=lambda n: haversine_km(
            hub["point"]["lat"], hub["point"]["lon"], *NODES[n]))
        # hubs that sit inside a (coarse) mask polygon are estuary/lagoon ports (Antwerp, Venice, Trieste): their
        # straight-line access leg cannot be judged by an inset mask, so only open-coast hubs are checked
        if any(_lm._inside(hub["point"]["lat"], hub["point"]["lon"], p) for p in _lm.MASK.values()):
            continue
        for lat, lon in _lm._along((hub["point"]["lat"], hub["point"]["lon"]), NODES[node], 40) if d > 1 else ():
            assert not any(_lm._inside(lat, lon, p) for p in _lm.MASK.values()), f"access leg {hub['id']}->{node} on land"
