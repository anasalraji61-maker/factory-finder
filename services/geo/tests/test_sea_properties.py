"""Property-style checks over (a deterministic sample of) all sea-hub pairs: no route may be nonsense."""
import itertools

import pytest

from ff_geo.domain.data import get_dataset
from ff_geo.domain.geometry import haversine_km
from ff_geo.domain.sea import EDGES, MAX_ACCESS_KM, NODES, _access, sea_distance_km

HUBS = sorted((h for h in get_dataset().hubs if h.type == "sea"), key=lambda h: h.id)
ALL_PAIRS = list(itertools.combinations(HUBS, 2))
PAIRS = ALL_PAIRS[::17]  # deterministic ~550-pair sample, covers every hub region
MAX_DETOUR = 8.0  # sea/great-circle; worst legit cases: Adriatic <-> Baltic, Gulf <-> Black Sea (~7)
HALF_EARTH_SEA_KM = 30000


def _d(a, b):
    return sea_distance_km(a.point.lat, a.point.lon, b.point.lat, b.point.lon)


def _gc(a, b):
    return haversine_km(a.point.lat, a.point.lon, b.point.lat, b.point.lon)


def test_sample_is_meaningful():
    assert len(HUBS) >= 138 and len(PAIRS) >= 500
    assert len({h.id for p in PAIRS for h in p}) >= 0.8 * len(HUBS)


@pytest.mark.parametrize(("a", "b"), PAIRS, ids=lambda h: getattr(h, "id", None))
def test_distance_at_least_great_circle_symmetric_and_bounded(a, b):
    km, path = _d(a, b)
    back, _ = _d(b, a)
    gc = _gc(a, b)
    assert km >= gc - 1e-6, "sea route shorter than the straight line"
    assert km == pytest.approx(back, abs=1e-6), "asymmetric distance"
    assert path and all(n in NODES for n in path)
    assert km < HALF_EARTH_SEA_KM
    if gc > 1000:
        assert km / gc <= MAX_DETOUR, f"detour {km / gc:.1f}x for {a.id}-{b.id}"


def test_same_port_is_near_zero_and_close_ports_are_close():
    for h in HUBS[::5]:
        km, _ = _d(h, h)
        assert 0 <= km <= 2 * MAX_ACCESS_KM * 1.15
    for a, b in ALL_PAIRS:
        if _gc(a, b) < 60:  # e.g. Yantian / Shekou
            assert _d(a, b)[0] < 500, (a.id, b.id)


def test_path_edges_exist_and_are_contiguous():
    edges = {frozenset(e) for e in EDGES}
    for a, b in PAIRS[::5]:
        _, path = _d(a, b)
        for x, y in itertools.pairwise(path):
            assert frozenset((x, y)) in edges, (a.id, b.id, x, y)


def test_access_never_jumps_overland_to_far_nodes():
    for h in HUBS:
        nodes = _access(h.point.lat, h.point.lon)
        assert nodes and len(nodes) <= 3
        assert all(d <= MAX_ACCESS_KM for d, _ in nodes[1:]), h.id


def test_further_along_a_lane_is_never_nearer_for_a_chain_of_hubs():
    chain = ["CNSHA", "SGSIN", "LKCMB", "AEJEA", "EGPSD", "NLRTM"]  # Far East -> Europe via Suez
    by_id = {h.id: h for h in HUBS}
    d = [_d(by_id[chain[0]], by_id[c])[0] for c in chain[1:]]
    assert d == sorted(d) and len(set(d)) == len(d)
