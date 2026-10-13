import pytest

from ff_geo.domain.data import Dataset, DatasetError, get_dataset

IRAQ = ["Baghdad", "Basra", "Erbil", "Mosul", "Najaf", "Karbala", "Sulaymaniyah", "Kirkuk",
        "Duhok", "Nasiriyah", "Amarah", "Diwaniyah", "Hillah", "Kut", "Samawah", "Ramadi",
        "Tikrit", "Baqubah"]


def test_sizes_and_uniqueness():
    ds = get_dataset()
    assert len(ds.countries) >= 45 and len(ds.cities) >= 150 and len(ds.hubs) >= 100
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
