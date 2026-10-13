import pytest

from ff_geo.domain.data import Dataset, DatasetError, get_dataset

IRAQ = ["Baghdad", "Basra", "Erbil", "Mosul", "Najaf", "Karbala", "Sulaymaniyah", "Kirkuk",
        "Duhok", "Nasiriyah", "Amarah", "Diwaniyah", "Hillah", "Kut", "Samawah", "Ramadi",
        "Tikrit", "Baqubah"]


def test_sizes_and_uniqueness():
    ds = get_dataset()
    assert len(ds.countries) >= 60 and len(ds.cities) >= 300 and len(ds.hubs) >= 170
    assert len({h.id for h in ds.hubs}) == len(ds.hubs)
    assert len({c.id for c in ds.cities}) == len(ds.cities)


def test_references_and_arabic():
    ds = get_dataset()
    for item in [*ds.cities, *ds.hubs]:
        assert item.country_code in ds.country_by_code
        assert item.name_ar.strip()
    assert all(c.name_ar and 1.2 <= c.road_factor <= 1.5 for c in ds.countries)


def test_all_iraqi_capitals():
    names = {c.name_en for c in get_dataset().cities if c.country_code == "IQ"}
    assert set(IRAQ) <= names


def test_required_hubs_present():
    ids = {h.id for h in get_dataset().hubs}
    for code in ["CNSHA", "CNNGB", "CNYTN", "IQUQR", "IQBSR", "TRMER", "AEJEA", "USLAX", "NLRTM",
                 "air:BGW", "air:PVG", "land:IBRAHIM_KHALIL", "land:TREBIL", "rail:DUI",
                 "consol:YIWU"]:
        assert code in ids


def test_invalid_data_rejected():
    ds = get_dataset()
    bad = ds.cities[0].model_copy(update={"country_code": "ZZ"})
    with pytest.raises(DatasetError):
        Dataset(ds.countries, [bad], ds.hubs)
    dup = [ds.hubs[0], ds.hubs[0]]
    with pytest.raises(DatasetError):
        Dataset(ds.countries, ds.cities, dup)


def test_coordinates_sane():
    ds = get_dataset()
    city = {c.name_en: c for c in ds.cities}
    # spot-check bounding boxes (lat, lon ranges)
    assert 32.5 < city["Baghdad"].point.lat < 34 and 44 < city["Baghdad"].point.lon < 45
    assert 120 < city["Shanghai"].point.lon < 122 and 30 < city["Shanghai"].point.lat < 32
    for h in ds.hubs:
        c = ds.country_by_code[h.country_code]
        assert c  # country exists
    hub = {h.id: h for h in ds.hubs}
    assert hub["IQUQR"].point.lat < 31 and hub["air:EBL"].point.lat > 36


def test_new_data_quality():
    ds = get_dataset()
    codes = {c.iso2 for c in ds.countries}
    assert {"SY", "LB", "LY", "DZ", "MA", "TN", "PK", "BD", "NG", "KE", "ZA", "BR", "AU"} <= codes
    assert all(c.name_ar.strip() and len(c.currency) == 3 for c in ds.countries)
    assert all(any("؀" <= ch <= "ۿ" for ch in x.name_ar) for x in [*ds.cities, *ds.hubs])
    # every country has at least one city; every city lies inside plausible global bounds
    assert codes <= {c.country_code for c in ds.cities}
    ids = [c.id for c in ds.cities]
    assert len(ids) == len(set(ids))
    # no two distinct cities of one country share exact coordinates
    seen = {}
    for c in ds.cities:
        key = (c.country_code, c.point.lat, c.point.lon)
        assert key not in seen, (c.id, seen.get(key))
        seen[key] = c.id
    # country bounding boxes for spot-checked countries (lat_min, lat_max, lon_min, lon_max)
    box = {"IQ": (28.9, 37.5, 38.7, 48.7), "CN": (18, 54, 73, 135), "US": (24, 49.5, -125, -66),
           "IN": (6, 36, 68, 98), "TR": (35.8, 42.2, 25.6, 44.9), "AU": (-44, -10, 112, 154),
           "BR": (-34, 5.5, -74, -34), "ZA": (-35, -22, 16, 33), "EG": (21.9, 31.7, 24.6, 36.9)}
    for item in [*ds.cities, *ds.hubs]:
        if item.country_code in box:
            la0, la1, lo0, lo1 = box[item.country_code]
            assert la0 <= item.point.lat <= la1 and lo0 <= item.point.lon <= lo1, item.id
