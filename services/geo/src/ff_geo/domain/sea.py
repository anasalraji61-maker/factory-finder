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
    # --- Japan Pacific coast ---
    "Osumi Strait": (30.5, 131.0),
    "Kii Channel": (33.9, 135.0),
    "Ise Bay Mouth": (34.3, 137.0),
    "Tokyo Bay Mouth": (35.0, 139.8),
    "Philippine Sea": (14.0, 136.0),
    "Luzon Strait": (20.5, 121.5),
    "Hawaii": (21.0, -158.0),
    # --- Black Sea ---
    "Bosphorus": (41.3, 29.2),
    "Black Sea West": (43.5, 29.8),
    "Constanta Approach": (44.1, 29.2),
    "Odesa Approach": (46.3, 31.0),
    "Black Sea East": (43.8, 36.5),
    "Novorossiysk Approach": (44.4, 37.5),
    # --- Africa: west, Cape, east ---
    "Morocco Atlantic": (33.8, -8.5),
    "Canary Islands": (28.0, -16.0),
    "Dakar Approach": (14.5, -18.0),
    "Guinea Offshore": (8.0, -17.5),
    "Cape Palmas Offshore": (3.5, -7.5),
    "Tema Approach": (5.0, 0.0),
    "Lagos Approach": (5.8, 3.4),
    "Bight of Bonny": (3.0, 7.5),
    "Gulf of Guinea South": (-3.0, 8.0),
    "Angola Offshore": (-12.0, 11.0),
    "Namibia Offshore": (-24.0, 12.5),
    "Cape Town Approach": (-34.0, 17.8),
    "Cape Agulhas": (-35.3, 20.0),
    "Agulhas East": (-35.5, 28.0),
    "Durban Approach": (-29.9, 31.4),
    "Mozambique Channel": (-17.0, 40.5),
    "Tanzania Offshore": (-6.8, 40.2),
    "Kenya Offshore": (-4.05, 40.2),
    "Somali Basin": (4.0, 52.0),
    "Indian Ocean Southwest": (-33.0, 50.0),
    "Indian Ocean Central": (-15.0, 75.0),
    "Southern Indian Ocean": (-35.0, 75.0),
    # --- South America ---
    "Cape Verde Passage": (15.0, -25.0),
    "Brazil Northeast": (-7.0, -33.0),
    "Brazil Southeast": (-22.0, -39.0),
    "Santos Approach": (-24.6, -45.5),
    "River Plate Approach": (-35.2, -56.0),
    "Anegada Passage": (18.5, -63.5),
    "Cartagena Approach": (10.2, -76.0),
    "Panama Atlantic": (9.6, -79.9),
    "Panama Pacific": (8.4, -79.5),
    "Central America Pacific": (9.0, -88.0),
    "Mexico Pacific": (18.0, -106.0),
    "Callao Approach": (-12.2, -77.5),
    # --- Australia / Indonesia ---
    "Sunda Strait": (-6.0, 105.8),
    "Java Sea": (-5.8, 110.5),
    "Karimata Strait": (-2.5, 108.5),
    "Java South": (-12.0, 108.0),
    "Fremantle Approach": (-32.3, 115.0),
    "Cape Leeuwin": (-35.2, 114.5),
    "Great Australian Bight": (-37.5, 128.0),
    "Port Phillip Approach": (-38.4, 144.7),
    "Bass Strait East": (-39.5, 148.5),
    "Sydney Approach": (-33.9, 152.0),
    "Coral Sea": (-20.0, 157.0),
    "Torres Strait": (-10.5, 142.2),
    "Arafura Sea": (-9.5, 130.0),
    "Banda Sea": (-6.5, 127.0),
    "Makassar Strait": (-2.0, 118.0),
    "Pacific Equatorial": (-4.0, 157.0),
    # --- Bay of Bengal / Bangladesh ---
    "Bay of Bengal Central": (12.0, 87.0),
    "Chennai Approach": (13.2, 81.0),
    "Head of Bay": (20.5, 89.5),
    "Chittagong Approach": (21.8, 91.6),
    # --- Southeast Asia gulf / Indonesia / Philippines ---
    "Gulf of Thailand": (10.0, 102.0),
    "Laem Chabang Approach": (12.8, 100.9),
    "Jakarta Approach": (-5.9, 106.8),
    "Madura Strait": (-6.9, 113.0),
    "Manila Approach": (14.3, 120.5),
    # --- Central Med / Tunisia / Libya / Adriatic ---
    "Gulf of Tunis": (37.2, 10.8),
    "Libya Offshore": (33.8, 14.5),
    "Otranto Strait": (40.0, 19.0),
    "Adriatic Central": (43.0, 15.5),
    "Adriatic North": (45.2, 13.2),
    # --- Baltic north / Scandinavia ---
    "Skagerrak": (57.8, 9.0),
    "Kattegat": (57.3, 11.3),
    "Oresund": (55.7, 12.7),
    "Baltic Central": (57.5, 19.5),
    "Gulf of Finland": (59.9, 26.5),
    # --- Black Sea south / east coast ---
    "Turkey Black Sea Coast": (41.9, 33.0),
    "Samsun Approach": (41.6, 36.3),
    "Poti Approach": (42.0, 41.0),
    # --- Arabian Sea / Oman ---
    "Duqm Approach": (19.3, 58.2),
    # --- Pacific South America / Cape Horn ---
    "Patagonia Offshore": (-47.0, -61.0),
    "Cape Horn": (-56.5, -67.0),
    "Chile South Offshore": (-50.0, -77.0),
    "Chile Offshore": (-33.0, -73.0),
    "Antofagasta Offshore": (-23.6, -71.0),
    # --- North America Pacific / Gulf ---
    "San Francisco Approach": (37.7, -123.0),
    "Gulf of Alaska": (50.0, -145.0),
    "Prince Rupert Approach": (54.0, -132.0),
    "Mississippi Passes": (28.9, -89.2),
    "Yucatan Channel": (21.8, -85.5),
    "Dardanelles": (40.0, 26.2),
    "Texas Offshore": (28.6, -94.3),
    # --- data round 4 (docs/requests/data-geo-sea-nodes.md): Caribbean, Red Sea, Africa, Med, Baltic, Oceania ---
    "Caribbean Passage": (16.5, -67.0),
    "Caucedo Approach": (17.6, -69.6),
    "Kingston Approach": (17.4, -76.8),
    "Guayaquil Approach": (-3.0, -81.0),
    "Peru North Offshore": (-5.0, -82.5),
    "Port Sudan Approach": (19.6, 38.5),
    "Israel Offshore": (32.3, 33.8),
    "Abidjan Approach": (4.6, -4.0),
    "Luanda Approach": (-9.0, 12.5),
    "Maputo Approach": (-26.0, 33.3),
    "Malta Offshore": (35.6, 14.9),
    "Baltic Northeast": (59.3, 21.0),
    "Tasman Sea": (-35.0, 160.0),
    "Northland Offshore": (-33.5, 174.5),
    "Auckland Approach": (-36.3, 176.0),
    "Fiji South": (-23.0, -179.5),
    "South Pacific Mid": (-15.0, -130.0),
    "Brisbane Approach": (-27.4, 154.2),
    "North Atlantic": (47.0, -35.0),
    "Windward Passage": (19.8, -73.8),
    "Old Bahama Channel": (23.2, -77.6),
    "Eastern Pacific": (-2.0, -110.0),
    "Yellow Sea North": (37.6, 124.5),
    "Jeju South": (32.8, 126.5),
    # --- land-mask QA fixes (tests/test_sea_landmask.py): keep lanes off peninsulas
    "Phillip Channel": (1.17, 103.55),
    "Malacca Strait South": (2.5, 101.1),
    "Cape Comorin Offshore": (7.0, 77.0),
    "Gulf of Panama South": (6.5, -79.7),
    "Cabo San Lucas Offshore": (22.2, -110.0),
    "Baja West Offshore": (26.0, -115.0),
    "Jutland Offshore": (56.0, 6.5),
    "Ras al Hadd Offshore": (22.4, 60.6),
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
    ("Singapore Strait", "Phillip Channel"),
    ("Phillip Channel", "Malacca Strait South"),
    ("Malacca Strait South", "Malacca Strait"),
    ("Malacca Strait", "Andaman Sea"),
    ("Andaman Sea", "Sri Lanka South"),
    ("Sri Lanka South", "Cape Comorin Offshore"),
    ("Cape Comorin Offshore", "Arabian Sea East"),
    ("Sri Lanka South", "Arabian Sea"),
    ("Arabian Sea East", "Indian Subcontinent West"),
    ("Arabian Sea East", "Arabian Sea"),
    ("Indian Subcontinent West", "Karachi Approach"),
    ("Karachi Approach", "Arabian Sea"),
    ("Arabian Sea", "Ras al Hadd Offshore"),
    ("Ras al Hadd Offshore", "Gulf of Oman"),
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
    # Japan Pacific coast
    ("East China Sea", "Osumi Strait"),
    ("Korea Strait", "Osumi Strait"),
    ("Osumi Strait", "Kii Channel"),
    ("Korea Strait", "Kii Channel"),
    ("Kii Channel", "Ise Bay Mouth"),
    ("Ise Bay Mouth", "Tokyo Bay Mouth"),
    ("Tokyo Bay Mouth", "North Pacific West"),
    ("Tokyo Bay Mouth", "Hawaii"),
    ("Hawaii", "US West Coast"),
    ("Osumi Strait", "Philippine Sea"),
    ("Philippine Sea", "Luzon Strait"),
    ("Luzon Strait", "Pearl River Estuary"),
    ("Philippine Sea", "Pacific Equatorial"),
    ("Philippine Sea", "East China Sea"),
    # Black Sea
    ("Marmara", "Bosphorus"),
    ("Bosphorus", "Black Sea West"),
    ("Black Sea West", "Constanta Approach"),
    ("Black Sea West", "Odesa Approach"),
    ("Constanta Approach", "Odesa Approach"),
    ("Black Sea West", "Black Sea East"),
    ("Black Sea East", "Novorossiysk Approach"),
    # Africa west / Cape / east
    ("Strait of Gibraltar", "Morocco Atlantic"),
    ("Morocco Atlantic", "Canary Islands"),
    ("Iberian Atlantic", "Canary Islands"),
    ("Canary Islands", "Dakar Approach"),
    ("Dakar Approach", "Cape Verde Passage"),
    ("Dakar Approach", "Guinea Offshore"),
    ("Guinea Offshore", "Cape Palmas Offshore"),
    ("Cape Palmas Offshore", "Tema Approach"),
    ("Tema Approach", "Lagos Approach"),
    ("Lagos Approach", "Bight of Bonny"),
    ("Bight of Bonny", "Gulf of Guinea South"),
    ("Gulf of Guinea South", "Angola Offshore"),
    ("Angola Offshore", "Namibia Offshore"),
    ("Namibia Offshore", "Cape Town Approach"),
    ("Cape Town Approach", "Cape Agulhas"),
    ("Cape Agulhas", "Agulhas East"),
    ("Agulhas East", "Durban Approach"),
    ("Durban Approach", "Mozambique Channel"),
    ("Mozambique Channel", "Tanzania Offshore"),
    ("Tanzania Offshore", "Kenya Offshore"),
    ("Mozambique Channel", "Kenya Offshore"),
    ("Kenya Offshore", "Somali Basin"),
    ("Somali Basin", "Gulf of Aden"),
    ("Somali Basin", "Sri Lanka South"),
    ("Somali Basin", "Arabian Sea"),
    ("Agulhas East", "Indian Ocean Southwest"),
    ("Durban Approach", "Indian Ocean Southwest"),
    ("Indian Ocean Southwest", "Indian Ocean Central"),
    ("Indian Ocean Central", "Sri Lanka South"),
    ("Agulhas East", "Southern Indian Ocean"),
    ("Indian Ocean Central", "Southern Indian Ocean"),
    ("Southern Indian Ocean", "Fremantle Approach"),
    # South America
    ("Canary Islands", "Brazil Northeast"),
    ("Cape Verde Passage", "Brazil Northeast"),
    ("Mid Atlantic", "Anegada Passage"),
    ("Brazil Northeast", "Brazil Southeast"),
    ("Brazil Southeast", "Santos Approach"),
    ("Santos Approach", "River Plate Approach"),
    ("Santos Approach", "Cape Town Approach"),
    ("Brazil Northeast", "Anegada Passage"),
    ("Anegada Passage", "Cartagena Approach"),
    ("Anegada Passage", "Florida Straits"),
    ("Cartagena Approach", "Panama Atlantic"),
    ("Panama Atlantic", "Panama Pacific"),
    ("Panama Pacific", "Guayaquil Approach"),
    ("Guayaquil Approach", "Peru North Offshore"),
    ("Peru North Offshore", "Callao Approach"),
    ("Panama Pacific", "Gulf of Panama South"),
    ("Gulf of Panama South", "Central America Pacific"),
    ("Central America Pacific", "Mexico Pacific"),
    ("Mexico Pacific", "Cabo San Lucas Offshore"),
    ("Cabo San Lucas Offshore", "Baja West Offshore"),
    ("Baja West Offshore", "US West Coast"),
    ("Hawaii", "Eastern Pacific"),
    ("Eastern Pacific", "Callao Approach"),
    # Australia / Indonesia
    ("Singapore Strait", "Karimata Strait"),
    ("Karimata Strait", "Java Sea"),
    ("Java Sea", "Sunda Strait"),
    ("Sunda Strait", "Java South"),
    ("Java South", "Fremantle Approach"),
    ("Fremantle Approach", "Cape Leeuwin"),
    ("Cape Leeuwin", "Great Australian Bight"),
    ("Great Australian Bight", "Port Phillip Approach"),
    ("Port Phillip Approach", "Bass Strait East"),
    ("Bass Strait East", "Sydney Approach"),
    ("Sydney Approach", "Coral Sea"),
    ("Coral Sea", "Torres Strait"),
    ("Torres Strait", "Arafura Sea"),
    ("Arafura Sea", "Banda Sea"),
    ("Banda Sea", "Makassar Strait"),
    ("Makassar Strait", "Java Sea"),
    ("Coral Sea", "Pacific Equatorial"),
    # Bay of Bengal
    ("Andaman Sea", "Bay of Bengal Central"),
    ("Bay of Bengal Central", "Sri Lanka South"),
    ("Bay of Bengal Central", "Chennai Approach"),
    ("Bay of Bengal Central", "Head of Bay"),
    ("Head of Bay", "Chittagong Approach"),
    # SE Asia gulf / Indonesia / Philippines
    ("Vietnam South Coast", "Gulf of Thailand"),
    ("Singapore Strait", "Gulf of Thailand"),
    ("Gulf of Thailand", "Laem Chabang Approach"),
    ("Java Sea", "Jakarta Approach"),
    ("Jakarta Approach", "Sunda Strait"),
    ("Java Sea", "Madura Strait"),
    ("South China Sea", "Manila Approach"),
    ("Manila Approach", "Luzon Strait"),
    # Tunisia / Libya / Adriatic
    ("Gulf of Tunis", "Central Mediterranean"),
    ("Gulf of Tunis", "West Mediterranean"),
    ("Libya Offshore", "Central Mediterranean"),
    ("Libya Offshore", "Gulf of Tunis"),
    ("Central Mediterranean", "Otranto Strait"),
    ("Otranto Strait", "Adriatic Central"),
    ("Adriatic Central", "Adriatic North"),
    # Baltic north
    ("German Bight", "Jutland Offshore"),
    ("Jutland Offshore", "Skagerrak"),
    ("Skagerrak", "Kattegat"),
    ("Kattegat", "Oresund"),
    ("Oresund", "Baltic South"),
    ("Baltic South", "Baltic Central"),
    ("Baltic Central", "Baltic Northeast"),
    ("Baltic Northeast", "Gulf of Finland"),
    # Black Sea south / east
    ("Bosphorus", "Turkey Black Sea Coast"),
    ("Turkey Black Sea Coast", "Samsun Approach"),
    ("Samsun Approach", "Black Sea East"),
    ("Black Sea East", "Poti Approach"),
    ("Samsun Approach", "Poti Approach"),
    # Oman
    ("Arabian Sea", "Duqm Approach"),
    ("Duqm Approach", "Ras al Hadd Offshore"),
    # Cape Horn / Chile
    ("River Plate Approach", "Patagonia Offshore"),
    ("Patagonia Offshore", "Cape Horn"),
    ("Cape Horn", "Chile South Offshore"),
    ("Chile South Offshore", "Chile Offshore"),
    ("Chile Offshore", "Antofagasta Offshore"),
    ("Antofagasta Offshore", "Callao Approach"),
    # North America Pacific / Gulf
    ("US West Coast", "San Francisco Approach"),
    ("San Francisco Approach", "North Pacific East"),
    ("North Pacific West", "Gulf of Alaska"),
    ("Gulf of Alaska", "North Pacific East"),
    ("Gulf of Alaska", "Prince Rupert Approach"),
    ("Prince Rupert Approach", "Puget Sound"),
    ("Gulf of Mexico", "Mississippi Passes"),
    # shortcuts that remove detours found by the property scan
    ("Luzon Strait", "Taiwan Strait"),
    ("Karimata Strait", "Jakarta Approach"),
    ("Ligurian Sea", "Gulf of Tunis"),
    ("East Mediterranean", "Otranto Strait"),
    ("Aegean Sea", "Dardanelles"),
    ("Dardanelles", "Marmara"),
    ("Gulf of Mexico", "Texas Offshore"),
    ("Texas Offshore", "Mississippi Passes"),
    ("Gulf of Mexico", "Yucatan Channel"),
    ("Yucatan Channel", "Panama Atlantic"),
    # data round 4
    ("Anegada Passage", "Caribbean Passage"),
    ("Caribbean Passage", "Caucedo Approach"),
    ("Caucedo Approach", "Kingston Approach"),
    ("Kingston Approach", "Cartagena Approach"),
    ("Kingston Approach", "Panama Atlantic"),
    ("Red Sea South", "Port Sudan Approach"),
    ("Port Sudan Approach", "Red Sea North"),
    ("East Mediterranean", "Israel Offshore"),
    ("Israel Offshore", "Levant Coast"),
    ("Cape Palmas Offshore", "Abidjan Approach"),
    ("Abidjan Approach", "Tema Approach"),
    ("Gulf of Guinea South", "Luanda Approach"),
    ("Luanda Approach", "Angola Offshore"),
    ("Durban Approach", "Maputo Approach"),
    ("Maputo Approach", "Mozambique Channel"),
    ("Central Mediterranean", "Malta Offshore"),
    ("Malta Offshore", "Libya Offshore"),
    ("US East Coast", "North Atlantic"),  # great-circle shortcut New York <-> Channel
    ("North Atlantic", "English Channel"),
    ("Dakar Approach", "Mid Atlantic"),
    ("Gulf of Guinea South", "Brazil Northeast"),
    ("Cape Palmas Offshore", "Brazil Northeast"),
    ("Anegada Passage", "US East Coast"),
    ("Kingston Approach", "Windward Passage"),
    ("Windward Passage", "Old Bahama Channel"),
    ("Old Bahama Channel", "Florida Straits"),
    ("Guayaquil Approach", "Central America Pacific"),
    ("Sydney Approach", "Northland Offshore"),
    ("Mid Atlantic", "North Atlantic"),
    ("Bohai/Yellow Sea", "Yellow Sea North"),  # Incheon / Korean west coast
    ("Yellow Sea North", "Jeju South"),
    ("Jeju South", "Korea Strait"),
    ("Java South", "Indian Ocean Central"),  # Sunda route: the Malacca bypass
    ("Sydney Approach", "Brisbane Approach"),
    ("Brisbane Approach", "Coral Sea"),
    ("Sydney Approach", "Tasman Sea"),
    ("Bass Strait East", "Tasman Sea"),
    ("Tasman Sea", "Northland Offshore"),
    ("Northland Offshore", "Auckland Approach"),
    ("Auckland Approach", "Fiji South"),
    ("Fiji South", "Hawaii"),
    ("Fiji South", "South Pacific Mid"),
    ("South Pacific Mid", "Callao Approach"),
    ("South Pacific Mid", "Panama Pacific"),
]

# Chokepoints: each one is a set of lane edges that `avoid=` removes. The edge cut sits on the side
# that keeps ports ON the strait (e.g. Bandar Abbas, Tangier Med, Port Said) reachable from outside.
CHOKEPOINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "suez": (("Gulf of Suez", "Port Said"),),
    "bab_el_mandeb": (("Gulf of Aden", "Bab-el-Mandeb"),),
    "hormuz": (("Strait of Hormuz", "Persian Gulf South"),),
    "malacca": (("Malacca Strait South", "Malacca Strait"),),
    "panama": (("Panama Atlantic", "Panama Pacific"),),
    "gibraltar": (("West Mediterranean", "Strait of Gibraltar"),),
    "bosphorus": (("Marmara", "Bosphorus"),),
}

# Quality of this lane graph (approximate shipping-lane waypoints, not charted routing).
DATA_CONFIDENCE = "low"
DATA_AS_OF = "2026-10"

MAX_ACCESS_KM = 400.0  # max straight-line from an endpoint to its nearest lane node
_ACCESS_FACTOR = 1.15


class SeaRouteUnavailable(ValueError):
    """No sea route exists under the requested `avoid` set."""


def parse_avoid(avoid: str | list[str] | tuple[str, ...] | None) -> frozenset[str]:
    """Normalise a comma-separated string / list of chokepoint ids; unknown ids raise ValueError."""
    if not avoid:
        return frozenset()
    items = avoid.split(",") if isinstance(avoid, str) else list(avoid)
    ids = frozenset(x.strip().lower().replace("-", "_") for x in items if x.strip())
    unknown = sorted(ids - CHOKEPOINTS.keys())
    if unknown:
        raise ValueError(f"unknown chokepoint(s): {', '.join(unknown)}; known: {', '.join(sorted(CHOKEPOINTS))}")
    return ids


@lru_cache(maxsize=32)
def _graph(avoid: frozenset[str] = frozenset()) -> dict[str, list[tuple[str, float]]]:
    blocked = {frozenset(e) for c in avoid for e in CHOKEPOINTS[c]}
    g: dict[str, list[tuple[str, float]]] = {n: [] for n in NODES}
    for a, b in EDGES:
        if frozenset((a, b)) in blocked:
            continue
        d = haversine_km(*NODES[a], *NODES[b]) * 1.05
        g[a].append((b, d))
        g[b].append((a, d))
    return g


@lru_cache(maxsize=2048)
def _access(lat: float, lon: float) -> tuple[tuple[float, str], ...]:
    """Nearest few lane nodes to a point (straight-line). Nodes farther than MAX_ACCESS_KM are dropped
    (except the nearest one), so a port never "jumps" overland to a node on another coast."""
    near = sorted((haversine_km(lat, lon, *p), n) for n, p in NODES.items())[:3]
    return tuple(x for i, x in enumerate(near) if i == 0 or x[0] <= MAX_ACCESS_KM)


@lru_cache(maxsize=4096)
def _dijkstra(start: str, goal: str, avoid: frozenset[str] = frozenset()) -> tuple[float, tuple[str, ...]]:
    """Shortest lane path (cached: the graph is static; at most 182^2 x |avoid sets| distinct keys, capped).
    Predecessor map instead of copying a path list per heap push."""
    g = _graph(avoid)
    dist: dict[str, float] = {start: 0.0}
    prev: dict[str, str] = {}
    pq: list[tuple[float, str]] = [(0.0, start)]
    done: set[str] = set()
    while pq:
        d, n = heapq.heappop(pq)
        if n in done:
            continue
        if n == goal:
            path = [n]
            while n != start:
                n = prev[n]
                path.append(n)
            return d, tuple(reversed(path))
        done.add(n)
        for m, w in g[n]:
            nd = d + w
            if m not in done and nd < dist.get(m, float("inf")):
                dist[m] = nd
                prev[m] = n
                heapq.heappush(pq, (nd, m))
    raise SeaRouteUnavailable("no sea route")


def sea_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float, avoid: frozenset[str] = frozenset()
) -> tuple[float, list[str]]:
    """Approximate sea distance (km) and the lane waypoints used.

    With `avoid` (chokepoint ids from CHOKEPOINTS) only each endpoint's nearest lane node is used, so a
    port can never "jump" overland to dodge a closure; raises SeaRouteUnavailable if no lane remains."""
    best: tuple[float, tuple[str, ...]] | None = None
    starts, goals = _access(lat1, lon1), _access(lat2, lon2)
    if avoid:
        starts, goals = starts[:1], goals[:1]
    for d1, n1 in starts:
        for d2, n2 in goals:
            try:
                core, path = (0.0, (n1,)) if n1 == n2 else _dijkstra(n1, n2, avoid)
            except SeaRouteUnavailable:
                continue
            total = core + (d1 + d2) * _ACCESS_FACTOR
            if best is None or total < best[0]:
                best = (total, path)
    if best is None:
        raise SeaRouteUnavailable(f"no sea route avoiding {', '.join(sorted(avoid))}")
    return best[0], list(best[1])
