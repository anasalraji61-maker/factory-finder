"""Data QA: coordinates vs country bounding boxes, ids, codes, Arabic names, alias ambiguity."""

import re
from collections import defaultdict

from ff_geo.domain.data import get_dataset
from ff_geo.domain.text import normalize

# iso2: (lat_min, lat_max, lon_min, lon_max) -- deliberately generous (incl. islands/territories)
BBOX: dict[str, tuple[float, float, float, float]] = {
    "CN": (18.0, 53.6, 73.5, 135.1), "IN": (6.7, 35.7, 68.0, 97.4), "US": (18.5, 71.5, -180.0, -66.0),
    "CA": (41.6, 83.2, -141.1, -52.0), "MX": (14.5, 32.8, -118.5, -86.7), "BR": (-33.8, 5.3, -74.0, -34.7),
    "AR": (-55.1, -21.7, -73.6, -53.6), "CL": (-56.0, -17.4, -75.7, -66.4), "CO": (-4.3, 13.5, -82.0, -66.8),
    "PE": (-18.4, 0.0, -81.4, -68.6), "EC": (-5.1, 1.5, -92.1, -75.2), "UY": (-35.0, -30.0, -58.5, -53.0),
    "PA": (7.2, 9.7, -83.1, -77.1), "DO": (17.5, 19.95, -72.1, -68.3), "JM": (17.7, 18.6, -78.4, -76.2),
    "GB": (49.8, 60.9, -8.7, 1.8), "DE": (47.2, 55.1, 5.8, 15.1), "FR": (41.3, 51.2, -5.2, 9.7),
    "ES": (27.5, 43.9, -18.3, 4.4), "PT": (32.3, 42.2, -31.5, -6.1), "IT": (35.4, 47.1, 6.6, 18.6),
    "NL": (50.7, 53.6, 3.3, 7.3), "BE": (49.5, 51.6, 2.5, 6.5), "CH": (45.8, 47.9, 5.9, 10.6),
    "AT": (46.3, 49.1, 9.5, 17.2), "PL": (49.0, 54.9, 14.1, 24.2), "CZ": (48.5, 51.1, 12.0, 18.9),
    "HU": (45.7, 48.6, 16.1, 22.9), "RO": (43.6, 48.3, 20.2, 29.8), "BG": (41.2, 44.3, 22.3, 28.7),
    "RS": (42.2, 46.2, 18.8, 23.1), "SI": (45.4, 46.9, 13.3, 16.6), "SK": (47.7, 49.7, 16.8, 22.6), "SE": (55.3, 69.1, 10.9, 24.2),
    "FI": (59.7, 70.1, 19.5, 31.6), "EE": (57.5, 59.7, 21.7, 28.3), "GR": (34.7, 41.8, 19.3, 28.3),
    "MT": (35.8, 36.1, 14.1, 14.6), "UA": (44.3, 52.4, 22.1, 40.3), "RU": (41.1, 81.9, 19.6, 180.0),
    "TR": (35.8, 42.2, 25.6, 44.9), "GE": (41.0, 43.6, 40.0, 46.8), "AZ": (38.3, 41.95, 44.7, 50.9),
    "KZ": (40.5, 55.5, 46.4, 87.4), "UZ": (37.1, 45.6, 55.9, 73.2), "IR": (25.0, 39.8, 44.0, 63.4),
    "IQ": (29.0, 37.4, 38.7, 48.7), "SA": (16.3, 32.2, 34.5, 55.7), "AE": (22.4, 26.2, 51.5, 56.5),
    "QA": (24.4, 26.3, 50.7, 51.7), "KW": (28.5, 30.2, 46.5, 48.5), "BH": (25.5, 26.4, 50.3, 50.9),
    "OM": (16.6, 26.5, 52.0, 59.9), "YE": (12.1, 19.0, 41.8, 54.6), "JO": (29.1, 33.4, 34.8, 39.4),
    "LB": (33.0, 34.7, 35.0, 36.7), "SY": (32.3, 37.4, 35.6, 42.4), "IL": (29.4, 33.4, 34.2, 35.9),
    "EG": (21.9, 31.7, 24.6, 36.9), "LY": (19.4, 33.2, 9.2, 25.2), "TN": (30.2, 37.6, 7.5, 11.7),
    "DZ": (18.9, 37.1, -8.7, 12.0), "MA": (20.7, 36.0, -17.2, -0.9), "SD": (8.6, 22.3, 21.8, 38.7),
    "DJ": (10.9, 12.8, 41.7, 43.5), "ET": (3.3, 15.0, 32.9, 48.0), "KE": (-4.8, 5.1, 33.8, 41.95),
    "TZ": (-11.8, -0.9, 29.3, 40.5), "UG": (-1.5, 4.3, 29.5, 35.1), "MZ": (-26.9, -10.4, 30.2, 40.9),
    "AO": (-18.1, -4.3, 11.6, 24.1), "ZA": (-34.9, -22.1, 16.4, 32.95), "NG": (4.2, 13.9, 2.6, 14.7),
    "GH": (4.7, 11.2, -3.3, 1.3), "CI": (4.3, 10.8, -8.7, -2.4), "SN": (12.2, 16.7, -17.6, -11.3),
    "TG": (6.0, 11.2, -0.2, 1.9), "AF": (29.3, 38.5, 60.4, 75.0), "PK": (23.6, 37.1, 60.8, 77.9),
    "BD": (20.6, 26.7, 88.0, 92.7), "LK": (5.9, 9.9, 79.6, 82.0), "TH": (5.6, 20.5, 97.3, 105.7),
    "VN": (8.4, 23.4, 102.1, 109.5), "MY": (0.8, 7.4, 99.6, 119.3), "SG": (1.15, 1.5, 103.6, 104.1),
    "PH": (4.5, 21.2, 116.9, 126.6), "ID": (-11.1, 6.1, 95.0, 141.1), "KR": (33.0, 38.7, 124.5, 131.0),
    "JP": (24.0, 45.6, 122.9, 146.0), "TW": (21.8, 25.4, 118.0, 122.1), "HK": (22.1, 22.6, 113.8, 114.5),
    "AU": (-43.7, -10.0, 112.9, 153.7), "NZ": (-47.5, -34.0, 166.0, 179.0),
}
ARABIC = re.compile(r"[؀-ۿ]")
# Cities that must have an Arabic-script name_ar
ARABIC_COUNTRIES = {"IQ", "TR", "SA", "AE", "QA", "KW", "BH", "OM"}


def _bad_bbox(items):
    out = []
    for i in items:
        b = BBOX.get(i.country_code)
        if b and not (b[0] <= i.point.lat <= b[1] and b[2] <= i.point.lon <= b[3]):
            out.append(f"{i.id} ({i.point.lat},{i.point.lon}) outside {i.country_code}")
    return out


def test_bbox_table_is_broad_and_valid():
    ds = get_dataset()
    assert len(BBOX) >= 60
    assert set(BBOX) <= set(ds.country_by_code)
    for b in BBOX.values():
        assert -90 <= b[0] < b[1] <= 90 and -180 <= b[2] < b[3] <= 180


def test_cities_inside_country_bbox():
    assert _bad_bbox(get_dataset().cities) == []


def test_hubs_inside_country_bbox():
    assert _bad_bbox(get_dataset().hubs) == []


def test_ids_unique_and_countries_exist():
    ds = get_dataset()
    for items in (ds.cities, ds.hubs):
        ids = [i.id for i in items]
        assert len(ids) == len(set(ids))
        assert all(i.country_code in ds.country_by_code for i in items)
    for h in ds.hubs:
        assert set(h.serves_countries) <= set(ds.country_by_code), h.id


def test_no_duplicate_coordinates_within_kind():
    ds = get_dataset()
    seen = {}
    dup = []
    for h in ds.hubs:
        k = (h.type, round(h.point.lat, 3), round(h.point.lon, 3))
        if k in seen:
            dup.append((seen[k], h.id))
        seen[k] = h.id
    assert dup == []


def test_port_unlocode_format_and_consistency():
    ds = get_dataset()
    codes = []
    for h in ds.hubs:
        if h.type == "sea":
            assert h.unlocode and re.fullmatch(r"[A-Z]{2}[A-Z2-9]{3}", h.unlocode), h.id
            assert len(h.unlocode) == 5
            assert h.unlocode[:2] == h.country_code, h.id
            assert h.id == h.unlocode, h.id
            codes.append(h.unlocode)
    assert len(codes) == len(set(codes))


def test_airport_iata_format_unique_and_ids():
    ds = get_dataset()
    codes = []
    for h in ds.hubs:
        if h.type == "air":
            assert h.iata and re.fullmatch(r"[A-Z]{3}", h.iata), h.id
            assert h.id == f"air:{h.iata}", h.id
            codes.append(h.iata)
    assert len(codes) == len(set(codes))


def test_arabic_names_for_key_regions():
    ds = get_dataset()
    missing = [
        c.id for c in ds.cities
        if c.country_code in ARABIC_COUNTRIES and not ARABIC.search(c.name_ar)
    ]
    assert missing == []
    assert [h.id for h in ds.hubs if not ARABIC.search(h.name_ar)] == []


def _alias_collisions():
    """normalized name/alias -> set of city ids within the same country (len > 1)."""
    ds = get_dataset()
    by = defaultdict(set)
    for c in ds.cities:
        for n in (c.name_en, c.name_ar, *ds.aliases.get(c.id, [])):
            by[(c.country_code, normalize(n))].add(c.id)
    return {k: v for k, v in by.items() if len(v) > 1}


def test_alias_ambiguity_candidates_reviewed():
    """Any same-country name/alias mapping to >1 city must be listed here as reviewed."""
    assert {k: sorted(v) for k, v in _alias_collisions().items()} == REVIEWED_AMBIGUITIES


# Genuine homonyms, kept as ambiguity candidates (search should return all, never auto-pick one).
REVIEWED_AMBIGUITIES: dict = {
    ("CN", normalize("تشانغتشو")): ["CN-CHANGZHOU", "CN-ZHANGZHOU"],  # 常州 / 漳州 share one Arabic rendering
    ("US", "springfield"): ["US-SPRINGFIELD_IL", "US-SPRINGFIELD_MA", "US-SPRINGFIELD_MO"],
    ("US", normalize("سبرينغفيلد")): ["US-SPRINGFIELD_IL", "US-SPRINGFIELD_MA", "US-SPRINGFIELD_MO"],
}
