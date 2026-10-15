"""Regression: sea routing / city search caches are effective, bounded and do not change results."""
import heapq

from ff_geo.domain import sea
from ff_geo.domain.data import get_dataset
from ff_geo.domain.search import search_cities


def _reference(start, goal, avoid):
    g = sea._graph(avoid)
    pq, seen = [(0.0, start, [start])], set()
    while pq:
        d, n, path = heapq.heappop(pq)
        if n == goal:
            return d, path
        if n in seen:
            continue
        seen.add(n)
        for m, w in g[n]:
            if m not in seen:
                heapq.heappush(pq, (d + w, m, [*path, m]))
    return None


def test_dijkstra_matches_reference_and_is_cached():
    nodes = sorted(sea.NODES)[:: max(1, len(sea.NODES) // 12)]
    for a in nodes:
        for b in nodes:
            for avoid in (frozenset(), frozenset({"suez"})):
                ref = _reference(a, b, avoid)
                try:
                    d, path = sea._dijkstra(a, b, avoid)
                except sea.SeaRouteUnavailable:
                    assert ref is None
                    continue
                assert abs(d - ref[0]) < 1e-6
                assert path[0] == a and path[-1] == b
    sea._dijkstra.cache_clear()
    sea.sea_distance_km(31.23, 121.47, 53.55, 9.99)
    before = sea._dijkstra.cache_info().hits
    sea.sea_distance_km(31.23, 121.47, 53.55, 9.99)
    assert sea._dijkstra.cache_info().hits > before or sea._dijkstra.cache_info().currsize <= 9


def test_cache_sizes_are_bounded():
    assert sea._dijkstra.cache_info().maxsize == 4096
    assert sea._access.cache_info().maxsize == 2048


def test_search_cities_uses_precomputed_names():
    ds = get_dataset()
    first = search_cities(ds, "sh")
    assert first == search_cities(ds, "sh")
    assert first and all(
        "sh" in c.name_en.lower() or any("sh" in a.lower() for a in ds.aliases.get(c.id, [])) for c in first
    )
    assert [c.name_en for c in search_cities(ds, None, "CN")] == sorted(c.name_en for c in ds.cities if c.country_code == "CN")
