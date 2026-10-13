import pytest

from ff_geo.domain.data import get_dataset
from ff_geo.domain.sea import EDGES, NODES, _graph, sea_distance_km

NEW_SEA_HUBS = [
    "KEMBA", "ZADUR", "ZACPT", "NGAPP", "GHTEM", "SNDKR", "UAODS", "ROCND", "RUNVS",
    "JPYOK", "JPOSA", "JPUKB", "JPNGO", "BRSSZ", "ARBUE", "PECLL", "COCTG", "AUSYD",
    "AUMEL", "AUFRE",
]


def _hub(hub_id):
    return {h.id: h for h in get_dataset().hubs}[hub_id].point


def _km(a, b):
    pa, pb = _hub(a), _hub(b)
    return sea_distance_km(pa.lat, pa.lon, pb.lat, pb.lon)


def test_graph_integrity():
    assert len(set(EDGES)) == len(EDGES)
    for a, b in EDGES:
        assert a in NODES and b in NODES and a != b
    for n, (lat, lon) in NODES.items():
        assert -90 <= lat <= 90 and -180 <= lon <= 180, n
    g = _graph()
    assert all(g[n] for n in NODES), "isolated node"
    seen, stack = set(), [next(iter(NODES))]
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack += [m for m, _ in g[n]]
    assert seen == set(NODES), "graph is not connected"


def test_new_sea_hubs_present_and_valid():
    hubs = {h.id: h for h in get_dataset().hubs}
    for code in NEW_SEA_HUBS:
        assert code in hubs and hubs[code].type == "sea" and hubs[code].unlocode == code
    assert sum(1 for h in hubs.values() if h.type == "sea") >= 114


@pytest.mark.parametrize(
    ("a", "b", "real_km", "tol"),
    [
        ("CNSHA", "NLRTM", 19500, 0.15),  # via Suez
        ("CNSHA", "IQUQR", 12000, 0.15),
        ("BRSSZ", "NLRTM", 9800, 0.15),
        ("ZADUR", "KEMBA", 3230, 0.15),  # ~1,745 nm; the 2,900 km quoted is straight-line
        ("CNSHA", "JPYOK", 1850, 0.15),
        ("SGSIN", "AUFRE", 4500, 0.15),
        ("NLRTM", "COCTG", 8900, 0.15),
        ("JPYOK", "USLAX", 8800, 0.15),
    ],
)
def test_known_sea_distances(a, b, real_km, tol):
    km, _ = _km(a, b)
    assert abs(km / real_km - 1) <= tol, (a, b, km)


def test_all_sea_hubs_routable_from_shanghai():
    sha = _hub("CNSHA")
    for h in get_dataset().hubs:
        if h.type != "sea":
            continue
        km, path = sea_distance_km(sha.lat, sha.lon, h.point.lat, h.point.lon)
        assert 0 <= km < 30000 and path, h.id


def test_new_regional_routes_use_expected_lanes():
    assert "Bosphorus" in _km("ROCND", "NLRTM")[1]
    assert "Cape Town Approach" in _km("NLRTM", "ZADUR")[1]
    assert 400 < _km("GHTEM", "NGAPP")[0] < 700
