"""Sea-network validation (data round 4): hub connectivity, a 40-pair route matrix, edge sanity,
chokepoints + the `avoid` option, data-quality labels. Pure offline; all data bundled."""
import math

import pytest
from fastapi.testclient import TestClient

from ff_geo.domain.data import get_dataset
from ff_geo.domain.geometry import haversine_km
from ff_geo.domain.sea import (
    CHOKEPOINTS,
    DATA_AS_OF,
    DATA_CONFIDENCE,
    EDGES,
    MAX_ACCESS_KM,
    NODES,
    SeaRouteUnavailable,
    _access,
    _graph,
    parse_avoid,
    sea_distance_km,
)
from ff_geo.main import create_app

HUBS = {h.id: h for h in get_dataset().hubs}
SEA_HUBS = [h for h in HUBS.values() if h.type == "sea"]


def km(a, b, avoid=frozenset()):
    pa, pb = HUBS[a].point, HUBS[b].point
    return sea_distance_km(pa.lat, pa.lon, pb.lat, pb.lon, avoid)


def gc(a, b):
    pa, pb = HUBS[a].point, HUBS[b].point
    return haversine_km(pa.lat, pa.lon, pb.lat, pb.lon)


# ---------------------------------------------------------------- ranges / labels
def test_all_coordinates_in_range():
    for n, (lat, lon) in NODES.items():
        assert -90 <= lat <= 90 and -180 <= lon <= 180, n
    for h in HUBS.values():
        assert -90 <= h.point.lat <= 90 and -180 <= h.point.lon <= 180, h.id


def test_sea_hubs_labelled_with_confidence_and_as_of_and_never_high():
    assert DATA_CONFIDENCE == "low" and DATA_AS_OF == "2026-10"
    for h in SEA_HUBS:
        assert h.confidence in {"low", "medium"}, h.id  # we never claim verification
        assert h.as_of == "2026-10", h.id


# ---------------------------------------------------------------- connectivity
def test_every_sea_hub_is_attached_to_the_graph_and_reachable_from_everywhere_else():
    anchors = ["CNSHA", "NLRTM", "USLAX", "BRSSZ", "AUSYD", "ZADUR"]
    for h in SEA_HUBS:
        near = _access(h.point.lat, h.point.lon)[0]
        assert near[0] <= 520, f"{h.id} is {near[0]:.0f} km from the nearest lane node"
        assert _graph()[near[1]], h.id
        for a in anchors:
            d, path = km(a, h.id)
            assert path and 0 <= d < 30000, (a, h.id)


REGIONS = {
    "iraq_gulf": ["IQUQR", "IQBSR", "IQFAO", "KWSWK", "SADMM", "BHKBS", "QAHMD", "AEJEA", "OMDQM"],
    "red_sea": ["SAJED", "SDPZU", "DJJIB", "YEADE", "EGSOK", "JOAQJ"],
    "east_africa": ["KEMBA", "TZDAR", "MZMPM", "ZADUR"],
    "west_africa": ["NGAPP", "GHTEM", "CIABJ", "TGLFW", "SNDKR", "AOLAD"],
    "mediterranean": ["ILHFA", "ILASH", "MTMAR", "SIKOP", "ITTRS", "TNRAD", "LYTIP", "EGALY", "ESVLC"],
    "black_sea": ["ROCND", "UAODS", "RUNVS", "GEPTI", "TRSAM", "BGVAR"],
    "baltic": ["SEGOT", "PLGDY", "FIHEL", "EETLL", "RULED"],
    "south_america": ["BRSSZ", "ARBUE", "CLVAP", "PECLL", "ECGYE", "COCTG"],
    "oceania": ["AUSYD", "AUMEL", "AUBNE", "AUFRE", "NZAKL"],
    "caribbean": ["JMKIN", "DOCAU", "PAMIT", "PABLB", "COCTG", "USMIA"],
}


@pytest.mark.parametrize("region", sorted(REGIONS))
def test_region_hubs_exist_and_route_to_each_other(region):
    ids = REGIONS[region]
    assert all(i in HUBS and HUBS[i].type == "sea" for i in ids)
    for a in ids:
        for b in ids:
            if a < b:
                assert km(a, b)[0] > 0 or gc(a, b) < 50


# ---------------------------------------------------------------- 40-pair matrix
# (a, b, published approx sea km, max/min tolerance vs published, max ratio sea/great-circle).
# Ratios are bounded by 2.2 except routes that physically must detour (Suez/Cape/Bosphorus/Panama).
PAIRS = [
    ("CNSHA", "NLRTM", 19500, 0.15, 2.5), ("CNSHA", "USLAX", 10700, 0.15, 2.2),
    ("CNYTN", "AEJEA", 9100, 0.20, 2.2), ("CNSHA", "IQUQR", 12000, 0.15, 2.2),
    ("SGSIN", "NLRTM", 15400, 0.15, 2.2), ("SGSIN", "AEJEA", 6700, 0.15, 2.2),
    ("AEJEA", "NLRTM", 11800, 0.15, 2.5), ("IQUQR", "NLRTM", 12200, 0.15, 3.3),
    ("IQUQR", "ITGOA", 10200, 0.15, 2.8), ("EGPSD", "ESALG", 3520, 0.15, 2.2),
    ("KRPUS", "USLGB", 9630, 0.15, 2.2), ("JPYOK", "USLAX", 8800, 0.15, 2.2),
    ("USNYC", "NLRTM", 5830, 0.20, 2.2), ("USHOU", "NLRTM", 9100, 0.20, 2.2),
    ("USHOU", "BRSSZ", 11100, 0.20, 2.2), ("BRSSZ", "ZACPT", 6300, 0.15, 2.2),
    ("ZACPT", "AUFRE", 8600, 0.15, 2.2), ("ZADUR", "INNSA", 7600, 0.15, 2.2),
    ("KEMBA", "INNSA", 5000, 0.15, 2.2), ("KEMBA", "AEJEA", 4630, 0.20, 2.2),
    ("NGAPP", "NLRTM", 7800, 0.15, 2.2), ("CIABJ", "BRSSZ", 6500, 0.25, 2.2),
    ("SNDKR", "USNYC", 5800, 0.20, 2.2), ("DJJIB", "AEJEA", 3250, 0.20, 2.2),
    ("ILHFA", "ITGOA", 3060, 0.15, 2.2), ("ROCND", "TRMER", 1850, 0.25, 2.6),
    ("UAODS", "NLRTM", 7600, 0.15, 3.6), ("RUNVS", "ITGOA", 3700, 0.15, 2.2),
    ("COCTG", "NLRTM", 8300, 0.20, 2.2), ("JMKIN", "USMIA", 1440, 0.30, 2.2),
    ("PABLB", "CNSHA", 16800, 0.15, 2.2), ("PAMIT", "USNYC", 3700, 0.25, 2.2),
    ("PECLL", "CNSHA", 18500, 0.15, 2.2), ("CLVAP", "BRSSZ", 7200, 0.15, 3.0),
    ("ECGYE", "USLAX", 6100, 0.15, 2.2), ("AUSYD", "NZAKL", 2150, 0.30, 2.2),
    ("AUBNE", "CNSHA", 8300, 0.15, 2.2), ("INMAA", "SGSIN", 3600, 0.15, 2.2),
    ("IDJKT", "CNSHA", 5000, 0.15, 2.2), ("MXZLO", "CNSHA", 12400, 0.15, 2.2),
]


def test_pair_matrix_has_40_pairs_over_many_ports():
    assert len(PAIRS) == 40 and len({p[:2] for p in PAIRS}) == 40
    assert len({x for p in PAIRS for x in p[:2]}) >= 40


@pytest.mark.parametrize(("a", "b", "real", "tol", "max_ratio"), PAIRS, ids=lambda x: x if isinstance(x, str) else None)
def test_pair_route_exists_and_is_plausible(a, b, real, tol, max_ratio):
    d, path = km(a, b)
    straight = gc(a, b)
    assert path
    assert d >= straight, "shorter than great-circle"
    assert 1.0 <= d / straight <= max_ratio, f"ratio {d / straight:.2f}"
    assert abs(d / real - 1) <= tol, f"{d:.0f} km vs published ~{real}"
    assert d == pytest.approx(km(b, a)[0], abs=1e-6)


# ---------------------------------------------------------------- edge sanity ("no land crossing")
OPEN_OCEAN = {  # nodes that legitimately anchor 3,500+ km crossings
    "Mid Atlantic", "North Atlantic", "North Pacific West", "North Pacific East", "Hawaii", "Fiji South",
    "South Pacific Mid", "Callao Approach", "Panama Pacific", "Pacific Equatorial", "Southern Indian Ocean",
    "Fremantle Approach", "Indian Ocean Central", "Indian Ocean Southwest", "Brazil Northeast",
    "Gulf of Guinea South", "Santos Approach", "Cape Town Approach", "Auckland Approach", "Northland Offshore",
    "Sydney Approach", "US West Coast", "US East Coast", "Iberian Atlantic", "Canary Islands", "Anegada Passage",
    "Tokyo Bay Mouth", "Eastern Pacific", "Philippine Sea", "Osumi Strait", "Gulf of Alaska", "Puget Sound", "Coral Sea",
    "Tasman Sea", "Java South", "Sri Lanka South", "Somali Basin", "Gulf of Aden", "Mexico Pacific",
    "San Francisco Approach", "Prince Rupert Approach", "Dakar Approach", "Cape Verde Passage",
    "Central America Pacific", "Guayaquil Approach", "Mozambique Channel", "Durban Approach",
    "Agulhas East", "Arabian Sea", "Arabian Sea East", "Bass Strait East", "Cape Agulhas", "Cape Leeuwin",
    "Great Australian Bight", "Port Phillip Approach", "Cape Palmas Offshore", "Gulf of Mexico", "Florida Straits",
    "River Plate Approach", "Patagonia Offshore", "Cape Horn", "Chile South Offshore", "Chile Offshore",
}
LAND_POLYGONS = {  # coarse, deliberately well inside the coasts (lat, lon)
    "sahara": [(18, -8), (18, 30), (30, 30), (30, -8)],
    "central_asia": [(32, 70), (32, 105), (48, 105), (48, 70)],
    "siberia": [(55, 60), (55, 140), (70, 140), (70, 60)],
    "north_america": [(30, -108), (30, -85), (55, -85), (55, -108)],
    "africa_interior": [(-15, 15), (-15, 35), (10, 35), (10, 15)],
    "arabia": [(19, 42), (19, 52), (25, 52), (25, 42)],
    "australia": [(-32, 125), (-32, 143), (-18, 143), (-18, 125)],
    "amazon": [(-12, -76), (-12, -60), (0, -60), (0, -76)],
    "andes_west": [(2, -77), (-4, -79.5), (-8, -78), (-12, -76), (-12, -60), (2, -60)],
    "india": [(15, 74), (15, 80), (26, 80), (26, 74)],
    "china": [(25, 105), (25, 115), (34, 115), (34, 105)],
    "europe": [(46.5, 6), (46.5, 22), (51, 22), (51, 6)],
}


def _inside(lat, lon, poly):
    c = False
    for (y1, x1), (y2, x2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _along(a, b, n=40):
    """Points on the great circle a->b (slerp)."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    v1 = (math.cos(la1) * math.cos(lo1), math.cos(la1) * math.sin(lo1), math.sin(la1))
    v2 = (math.cos(la2) * math.cos(lo2), math.cos(la2) * math.sin(lo2), math.sin(la2))
    w = math.acos(max(-1, min(1, sum(x * y for x, y in zip(v1, v2, strict=True)))))
    for i in range(n + 1):
        t = i / n
        k1, k2 = math.sin((1 - t) * w) / math.sin(w), math.sin(t * w) / math.sin(w)
        v = [k1 * x + k2 * y for x, y in zip(v1, v2, strict=True)]
        yield math.degrees(math.asin(v[2])), math.degrees(math.atan2(v[1], v[0]))


def test_edge_lengths_are_sane():
    for a, b in EDGES:
        d = haversine_km(*NODES[a], *NODES[b])
        assert d <= 7500, (a, b, d)
        if d > 3500:
            assert a in OPEN_OCEAN and b in OPEN_OCEAN, f"long edge {a}-{b} ({d:.0f} km) between non-ocean nodes"


def test_no_node_or_edge_crosses_deep_land():
    for n, (lat, lon) in NODES.items():
        for name, poly in LAND_POLYGONS.items():
            assert not _inside(lat, lon, poly), f"node {n} inside {name}"
    for a, b in EDGES:
        for lat, lon in _along(NODES[a], NODES[b]):
            for name, poly in LAND_POLYGONS.items():
                assert not _inside(lat, lon, poly), f"edge {a}-{b} crosses {name} at {lat:.1f},{lon:.1f}"


def test_access_legs_are_short():
    for h in SEA_HUBS:
        assert all(d <= MAX_ACCESS_KM for d, _ in _access(h.point.lat, h.point.lon)[1:]), h.id


# ---------------------------------------------------------------- chokepoints / avoid
def test_all_required_chokepoints_modelled_with_valid_edges():
    assert {"suez", "bab_el_mandeb", "hormuz", "malacca", "panama", "gibraltar"} <= set(CHOKEPOINTS)
    edges = {frozenset(e) for e in EDGES}
    for name, cut in CHOKEPOINTS.items():
        assert cut and all(frozenset(e) in edges for e in cut), name


# (chokepoint, origin, destination, waypoint normally used)
USES = [
    ("suez", "CNSHA", "NLRTM", "Port Said"),
    ("bab_el_mandeb", "CNSHA", "EGPSD", "Bab-el-Mandeb"),
    ("hormuz", "SGSIN", "IQUQR", "Strait of Hormuz"),
    ("malacca", "CNSHA", "INNSA", "Malacca Strait"),
    ("panama", "USNYC", "PECLL", "Panama Atlantic"),
    ("gibraltar", "EGPSD", "NLRTM", "Strait of Gibraltar"),
]


@pytest.mark.parametrize(("choke", "a", "b", "waypoint"), USES)
def test_avoid_removes_chokepoint_or_reports_unavailable(choke, a, b, waypoint):
    base, path = km(a, b)
    assert waypoint in path, "test pair should use the chokepoint"
    try:
        d, alt = km(a, b, frozenset({choke}))
    except SeaRouteUnavailable:
        assert choke == "hormuz"  # Gulf ports are only reachable through Hormuz
        return
    cut = {frozenset(e) for e in CHOKEPOINTS[choke]}
    assert not any(frozenset(p) in cut for p in zip(alt, alt[1:], strict=False)), alt
    assert d > base, "a detour must be longer than the direct lane"


def test_known_detours_are_plausible():
    base = km("CNSHA", "NLRTM")[0]
    assert "Panama Atlantic" in km("CNSHA", "NLRTM", frozenset({"suez"}))[1]  # transpacific + Panama is shorter
    cape = km("CNSHA", "NLRTM", frozenset({"suez", "panama"}))
    assert "Cape Agulhas" in cape[1] and 1.2 < cape[0] / base < 1.6  # real: ~ +3,000 nm of ~10,500
    sunda = km("SGSIN", "INNSA", frozenset({"malacca"}))
    assert "Sunda Strait" in sunda[1] and "Malacca Strait" not in sunda[1]
    horn = km("BRSSZ", "PECLL", frozenset({"panama"}))
    assert "Cape Horn" in horn[1]
    # Gibraltar closed: the Med is only reachable around Africa via Suez
    med = km("NLRTM", "EGPSD", frozenset({"gibraltar"}))
    assert "Strait of Gibraltar" not in med[1] and med[0] > 2.5 * km("NLRTM", "EGPSD")[0]


def test_avoid_hormuz_blocks_gulf_ports_but_not_the_outside():
    with pytest.raises(SeaRouteUnavailable):
        km("CNSHA", "IQUQR", frozenset({"hormuz"}))
    assert km("CNSHA", "AEFJR", frozenset({"hormuz"}))[0] > 0  # Fujairah is outside
    with pytest.raises(SeaRouteUnavailable):
        km("CNSHA", "ROCND", frozenset({"bosphorus"}))


def test_avoid_is_a_noop_without_options_and_parse_rules():
    assert km("CNSHA", "NLRTM") == km("CNSHA", "NLRTM", frozenset())
    assert parse_avoid(None) == parse_avoid("") == frozenset()
    assert parse_avoid("Suez, bab-el-mandeb") == {"suez", "bab_el_mandeb"}
    with pytest.raises(ValueError, match="unknown chokepoint"):
        parse_avoid("suez,narnia")


# ---------------------------------------------------------------- HTTP surface
@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def _q(a, b, **extra):
    pa, pb = HUBS[a].point, HUBS[b].point
    return {"from_lat": pa.lat, "from_lon": pa.lon, "to_lat": pb.lat, "to_lon": pb.lon, "mode": "sea", **extra}


def test_api_avoid_suez(client):
    base = client.get("/v1/distance", params=_q("CNSHA", "NLRTM")).json()
    r = client.get("/v1/distance", params=_q("CNSHA", "NLRTM", avoid="suez")).json()
    assert base["avoided"] == [] and r["avoided"] == ["suez"]
    assert "Port Said" in base["via"] and "Port Said" not in r["via"]
    assert r["distance_km"] > base["distance_km"]
    assert r["confidence"] == "low" and r["as_of"] == "2026-10" and r["is_estimate"] is True


def test_api_avoid_errors(client):
    r = client.get("/v1/distance", params=_q("CNSHA", "NLRTM", avoid="narnia"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_chokepoint"
    r = client.get("/v1/distance", params=_q("CNSHA", "IQUQR", avoid="hormuz"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "sea_route_unavailable"


def test_api_avoid_ignored_for_non_sea_modes(client):
    q = _q("CNSHA", "NLRTM", avoid="suez")
    q["mode"] = "air"
    assert client.get("/v1/distance", params=q).json()["avoided"] == []
