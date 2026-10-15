"""Stricter offline land check for the sea lane graph (QA follow-up).

Hand-written *inset* landmass polygons (every vertex deliberately 0.3-1.5 degrees inland of the real
coast, no gulfs/seas inside them). Every lane node and every sampled point of every edge's great circle
must stay outside all polygons. Edges that legitimately thread a strait are allowlisted by id (and the
strait nodes themselves sit outside every polygon). Limits: islands (Sicily, Sardinia, Japan, Indonesia,
Philippines, ...) are mostly not covered; polygons are inset so near-coast grazing (< ~30 km) is NOT
detected. This is a sanity net, not a coastline model.  Coordinates are (lat, lon)."""
import math

import pytest

from ff_geo.domain.sea import EDGES, NODES


def _inside(lat, lon, poly):
    c = False
    for (y1, x1), (y2, x2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _along(a, b, n=80):
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

MASK = {
    # ---- Africa (mainland, inset from Atlantic/Med/Red Sea/Indian Ocean coasts)
    "africa": [
        (29, -8), (29.5, 10), (29.5, 22), (28.5, 31), (22, 34), (19, 35), (16, 37), (14, 38), (9.5, 45),
        (8, 49), (6, 47), (2, 44), (-1, 39), (-5, 37), (-10, 38), (-15, 37), (-20, 34), (-24, 33),
        (-28, 31), (-31, 28), (-33, 26), (-33, 24), (-33, 20), (-31, 18), (-27, 16.5), (-22, 15.5),
        (-15, 13), (-12, 15), (-6, 14), (-2, 12), (1, 11), (4, 12), (6, 9), (7, 6), (7.5, 2), (8, 0),
        (8, -3), (7, -6), (7.5, -9), (10, -12), (12, -14), (14, -15), (16, -14), (18, -14), (22, -13),
        (25, -12), (28, -9),
    ],
    "iberia": [(43, -6), (42.5, -1), (41, 0), (39.5, -1.5), (38.2, -1.8), (37.4, -3.5), (37.4, -5.5),
               (37.5, -7), (38.5, -8.2), (41, -8), (42.5, -7.8)],
    "w_europe": [(48.2, -2), (48.7, -0.5), (49.6, 2), (50.3, 3), (50.9, 3.8), (51.8, 5), (52.8, 6.5),
                 (52.9, 8.5), (53.4, 9.8), (53.6, 10.8), (53.8, 12.5), (53.5, 14.5), (53.8, 16.5),
                 (53.8, 20), (54.5, 22), (54.5, 26), (50, 26), (47, 25.5), (45, 26), (43.5, 25),
                 (41.5, 24.5), (41.2, 22), (42, 20), (43.5, 17.5), (44.5, 15.5), (45.5, 14), (45, 11.5),
                 (44.6, 8.5), (43.9, 6), (43.9, 4), (43.2, 2.5), (42.8, 0), (43.4, -0.8), (45.7, -0.3),
                 (47.2, -1.2), (47.7, -2)],
    "italy": [(44.3, 10.5), (43.8, 11.8), (42.8, 13.3), (41.9, 14.8), (41, 15.6), (41.2, 14.3),
              (41.8, 13), (42.3, 12), (42.9, 11.4), (43.4, 10.9), (43.8, 10.6)],
    "sicily_core": [(37.6, 13.6), (37.85, 14.2), (37.8, 14.9), (37.5, 14.8), (37.3, 14.5), (37.4, 13.8)],
    "great_britain": [(51.2, -2.2), (51.2, -1), (51.5, 0), (52.2, 0.8), (52.7, -0.3), (53.3, -0.8), (54, -1.2),
                      (54.8, -1.8), (55.3, -2.2), (54.8, -3), (54, -2.6), (53.6, -2.7), (53.1, -2.8),
                      (52.5, -3), (51.8, -3)],
    "jutland": [(55.3, 9.0), (56.6, 8.4), (57.0, 9.3), (56.2, 10.2), (55.4, 9.6)],
    "anatolia": [(37.4, 31), (38.4, 28.2), (39.5, 27.8), (40, 29.3), (40.7, 31), (40.8, 33), (40.9, 35),
                 (40.8, 37.5), (40.5, 40.5), (39.5, 43), (37.8, 43), (37, 38), (37.2, 35.5), (37.4, 33.5)],
    "arabia": [(16, 44.5), (19, 41.5), (22, 40.5), (25, 38.8), (27.5, 37), (30, 37), (30, 46), (29.5, 47),
               (28, 47.5), (26.5, 49), (24.3, 51.5), (23.5, 53), (23.8, 55), (23, 57), (22, 58.5),
               (20.5, 57.5), (19, 56.5), (18, 54), (17.5, 51), (17.5, 49), (16.5, 47)],
    "india": [(24.5, 71.5), (23, 73), (21, 73.5), (19, 74), (16, 74.5), (13, 75.5), (10.5, 76.5),
              (9, 76.8), (8.6, 77.3), (9.2, 78), (10.5, 78.6), (12, 79), (13.5, 79.5), (15, 79.3),
              (17, 81.5), (18.5, 83.5), (20.5, 85.5), (22, 86.5), (25.5, 86), (25.5, 74)],
    "malay_peninsula": [(6.2, 100.7), (6, 102), (5.2, 102.8), (4.3, 103.1), (3.3, 103.05), (2.5, 103.4),
                        (1.7, 103.5), (2.2, 102.5), (3, 101.7), (4.8, 101)],
    "baja_sur_core": [(24.6, -111.6), (25.2, -111.6), (25.2, -111.2), (24.6, -111.2)],
    "panama_west_core": [(8.45, -82.2), (8.75, -82.2), (8.75, -81), (8.45, -81)],
    # ---- the coarse inland polygons of test_sea_network (kept; still enforced there)
    "us_east_core": [(30.8, -90.5), (31, -88), (30.8, -85.5), (30.5, -83.5), (29.5, -82), (28, -81.5),
                     (27, -81), (30.3, -82), (32, -81.7), (33.5, -80.5), (35, -77.8), (36.5, -77.5),
                     (39.5, -77), (40.6, -74.5), (42.2, -71.5), (46.5, -69), (46.5, -84), (40, -90)],
    "us_west_core": [(47.5, -121.5), (44, -123), (41, -123.2), (38.5, -121.8), (37, -121.5), (35.4, -120.5),
                     (34.7, -120), (34.25, -118.5), (33.7, -117.4), (33.3, -116.8), (32.9, -116.8),
                     (33, -114.5), (37, -109), (47.5, -109)],
    "south_america": [(10, -72), (9, -62), (4, -52), (-1, -50.5), (-4, -41), (-7, -38), (-12, -40),
                      (-17, -41), (-21, -42), (-24, -47), (-27, -50), (-31, -54), (-34, -57), (-38, -62),
                      (-42, -66), (-46, -68), (-50, -70), (-52, -71), (-45, -72), (-38, -72), (-30, -70.7),
                      (-20, -69.8), (-15, -73.5), (-10, -77), (-5, -79), (-1, -78.5), (3, -76.5), (7, -75)],
    "australia": [(-12.5, 131), (-12.5, 136), (-16, 140), (-20, 147), (-24, 150), (-29, 152), (-34, 150),
                  (-37, 148), (-37, 143), (-36, 138), (-34, 135.5), (-32.5, 133), (-32, 124), (-33.5, 118),
                  (-34, 116), (-30, 115.5), (-24, 114.5), (-21, 117), (-19, 121.5), (-17.5, 125),
                  (-15, 128), (-13.5, 130)],
}

# Edges that deliberately thread a strait/canal or hug an island chain; keyed by the (unordered) node pair.
ALLOW: set[frozenset[str]] = set()


def _hits(a, b):
    out = []
    for lat, lon in _along(NODES[a], NODES[b], 80):
        for name, poly in MASK.items():
            if _inside(lat, lon, poly):
                out.append((name, round(lat, 1), round(lon, 1)))
                break
    return out


def test_mask_polygons_are_well_formed():
    for name, poly in MASK.items():
        assert len(poly) >= 4, name
        for lat, lon in poly:
            assert -90 <= lat <= 90 and -180 <= lon <= 180, name


def test_no_lane_node_inside_an_inset_landmass():
    bad = [(n, name) for n, (lat, lon) in NODES.items() for name, p in MASK.items() if _inside(lat, lon, p)]
    assert not bad, bad


@pytest.mark.parametrize("a,b", [e for e in EDGES if frozenset(e) not in ALLOW], ids=lambda x: str(x))
def test_edge_great_circle_stays_off_inset_landmasses(a, b):
    hits = _hits(a, b)
    assert not hits, f"edge {a} -> {b} enters {hits[:3]}"


def test_allowlist_references_real_edges():
    real = {frozenset(e) for e in EDGES}
    assert real >= ALLOW
