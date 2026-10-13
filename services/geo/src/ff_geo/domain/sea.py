"""Approximate sea distances via a small waypoint graph of major shipping lanes."""

import heapq
from functools import lru_cache

from .geometry import haversine_km

# name: (lat, lon)
NODES: dict[str, tuple[float, float]] = {
    "Bohai/Yellow Sea": (38.0, 122.0),
    "East China Sea": (30.5, 124.0),
    "Taiwan Strait": (24.5, 119.5),
    "Pearl River Estuary": (21.5, 114.5),
    "South China Sea": (14.0, 112.0),
    "Vietnam South Coast": (9.5, 108.0),
    "Gulf of Tonkin": (19.5, 107.5),
    "Singapore Strait": (1.2, 104.3),
    "Malacca Strait": (4.5, 99.5),
    "Andaman Sea": (7.0, 92.0),
    "Sri Lanka South": (5.5, 80.5),
    "Arabian Sea East": (17.0, 70.0),
    "Arabian Sea": (14.0, 60.0),
    "Gulf of Oman": (25.0, 58.5),
    "Strait of Hormuz": (26.4, 56.6),
    "Persian Gulf South": (25.8, 53.5),
    "Persian Gulf Central": (27.5, 50.8),
    "Persian Gulf Head": (29.6, 49.2),
    "Gulf of Aden": (12.3, 47.0),
    "Bab-el-Mandeb": (12.6, 43.3),
    "Red Sea South": (18.5, 40.5),
    "Red Sea North": (27.5, 34.0),
    "Gulf of Aqaba": (28.7, 34.8),
    "Gulf of Suez": (29.7, 32.6),
    "Port Said": (31.5, 32.4),
    "East Mediterranean": (33.5, 29.0),
    "Levant Coast": (35.5, 34.0),
    "Aegean Sea": (37.0, 25.5),
    "Marmara": (40.8, 28.3),
    "Central Mediterranean": (35.0, 18.0),
    "Ligurian Sea": (43.0, 8.8),
    "West Mediterranean": (38.5, 4.0),
    "Strait of Gibraltar": (36.0, -5.6),
    "Iberian Atlantic": (38.0, -11.0),
    "Bay of Biscay": (46.5, -6.0),
    "English Channel": (49.8, -3.0),
    "Dover Strait": (51.0, 1.8),
    "North Sea": (52.3, 3.2),
    "German Bight": (54.2, 7.5),
    "Baltic South": (55.0, 15.5),
    "Mid Atlantic": (38.0, -45.0),
    "US East Coast": (38.5, -72.5),
    "US Southeast": (31.0, -79.0),
    "Florida Straits": (25.0, -80.0),
    "Gulf of Mexico": (26.0, -91.0),
    "North Pacific West": (42.0, 160.0),
    "North Pacific East": (40.0, -150.0),
    "US West Coast": (33.3, -118.8),
    "Puget Sound": (48.3, -123.5),
    "Korea Strait": (34.0, 129.5),
    "Indian Subcontinent West": (22.0, 68.5),
    "Karachi Approach": (24.3, 66.7),
}

EDGES: list[tuple[str, str]] = [
    ("Bohai/Yellow Sea", "East China Sea"),
    ("East China Sea", "Taiwan Strait"),
    ("East China Sea", "Korea Strait"),
    ("Taiwan Strait", "Pearl River Estuary"),
    ("Pearl River Estuary", "South China Sea"),
    ("Gulf of Tonkin", "South China Sea"),
    ("South China Sea", "Vietnam South Coast"),
    ("Vietnam South Coast", "Singapore Strait"),
    ("South China Sea", "Singapore Strait"),
    ("Singapore Strait", "Malacca Strait"),
    ("Malacca Strait", "Andaman Sea"),
    ("Andaman Sea", "Sri Lanka South"),
    ("Sri Lanka South", "Arabian Sea East"),
    ("Sri Lanka South", "Arabian Sea"),
    ("Arabian Sea East", "Indian Subcontinent West"),
    ("Arabian Sea East", "Arabian Sea"),
    ("Indian Subcontinent West", "Karachi Approach"),
    ("Karachi Approach", "Arabian Sea"),
    ("Arabian Sea", "Gulf of Oman"),
    ("Gulf of Oman", "Strait of Hormuz"),
    ("Strait of Hormuz", "Persian Gulf South"),
    ("Persian Gulf South", "Persian Gulf Central"),
    ("Persian Gulf Central", "Persian Gulf Head"),
    ("Arabian Sea", "Gulf of Aden"),
    ("Sri Lanka South", "Gulf of Aden"),
    ("Gulf of Aden", "Bab-el-Mandeb"),
    ("Bab-el-Mandeb", "Red Sea South"),
    ("Red Sea South", "Red Sea North"),
    ("Red Sea North", "Gulf of Aqaba"),
    ("Red Sea North", "Gulf of Suez"),
    ("Gulf of Suez", "Port Said"),
    ("Port Said", "East Mediterranean"),
    ("East Mediterranean", "Levant Coast"),
    ("East Mediterranean", "Aegean Sea"),
    ("Aegean Sea", "Marmara"),
    ("Aegean Sea", "Central Mediterranean"),
    ("East Mediterranean", "Central Mediterranean"),
    ("Central Mediterranean", "Ligurian Sea"),
    ("Central Mediterranean", "West Mediterranean"),
    ("Ligurian Sea", "West Mediterranean"),
    ("West Mediterranean", "Strait of Gibraltar"),
    ("Strait of Gibraltar", "Iberian Atlantic"),
    ("Iberian Atlantic", "Bay of Biscay"),
    ("Bay of Biscay", "English Channel"),
    ("English Channel", "Dover Strait"),
    ("Dover Strait", "North Sea"),
    ("North Sea", "German Bight"),
    ("German Bight", "Baltic South"),
    ("Iberian Atlantic", "Mid Atlantic"),
    ("Mid Atlantic", "US East Coast"),
    ("US East Coast", "US Southeast"),
    ("US Southeast", "Florida Straits"),
    ("Florida Straits", "Gulf of Mexico"),
    ("Korea Strait", "North Pacific West"),
    ("East China Sea", "North Pacific West"),
    ("North Pacific West", "North Pacific East"),
    ("North Pacific East", "US West Coast"),
    ("North Pacific East", "Puget Sound"),
]

MAX_ACCESS_KM = 400.0  # max straight-line from an endpoint to its nearest lane node
_ACCESS_FACTOR = 1.15


@lru_cache(maxsize=1)
def _graph() -> dict[str, list[tuple[str, float]]]:
    g: dict[str, list[tuple[str, float]]] = {n: [] for n in NODES}
    for a, b in EDGES:
        d = haversine_km(*NODES[a], *NODES[b]) * 1.05
        g[a].append((b, d))
        g[b].append((a, d))
    return g


def _access(lat: float, lon: float) -> list[tuple[float, str]]:
    """Nearest few lane nodes to a point (straight-line)."""
    return sorted((haversine_km(lat, lon, *p), n) for n, p in NODES.items())[:3]


def _dijkstra(start: str, goal: str) -> tuple[float, list[str]]:
    g = _graph()
    pq: list[tuple[float, str, list[str]]] = [(0.0, start, [start])]
    seen: set[str] = set()
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
    raise ValueError("no sea route")


def sea_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, list[str]]:
    """Approximate sea distance (km) and the lane waypoints used."""
    best: tuple[float, list[str]] | None = None
    for d1, n1 in _access(lat1, lon1):
        for d2, n2 in _access(lat2, lon2):
            core, path = (0.0, [n1]) if n1 == n2 else _dijkstra(n1, n2)
            total = core + (d1 + d2) * _ACCESS_FACTOR
            if best is None or total < best[0]:
                best = (total, path)
    assert best is not None
    return best
