from ff_geo.domain.data import get_dataset
from ff_geo.domain.distance import compute_distance
from ff_geo.domain.geometry import haversine_km
from ff_geo.domain.search import nearest_hubs, search_cities
from ff_geo.domain.text import normalize

ds = get_dataset()
city = {c.name_en: c.point for c in ds.cities}


def test_normalize_arabic():
    assert normalize("أَرْبِيل") == normalize("اربيل")
    assert normalize("كربلاء") == "كربلاء"
    assert normalize("مـــوصل") == "موصل"
    assert normalize("البصرة") == normalize("البصره")
    assert normalize("إسطنبول") == normalize("اسطنبول")
    assert normalize("سامرّاء") == normalize("سامراء")


def test_city_search_arabic_variants():
    assert search_cities(ds, "اربيل")[0].name_en == "Erbil"
    assert search_cities(ds, "الحله")[0].name_en == "Hillah"
    assert search_cities(ds, "ba")[0].name_en in {"Baghdad", "Baqubah", "Basra", "Bangalore", "Baku",
                                                  "Bandar Abbas", "Bangkok"}
    assert {c.name_en for c in search_cities(ds, "baghdad", "IQ")} == {"Baghdad"}
    assert search_cities(ds, "baghdad", "CN") == []
    assert len(search_cities(ds, None, "IQ")) >= 18


def test_haversine_known():
    # London - Paris ~ 344 km
    assert 340 < haversine_km(51.5074, -0.1278, 48.8566, 2.3522) < 348


def test_nearest_sea_hubs():
    p = city["Shanghai"]
    assert nearest_hubs(ds, p.lat, p.lon, "sea", 1)[0].id == "CNSHA"
    y = city["Yiwu"]
    assert nearest_hubs(ds, y.lat, y.lon, "sea", 1)[0].id == "CNNGB"
    b = city["Basra"]
    assert nearest_hubs(ds, b.lat, b.lon, "sea", 1, country="IQ")[0].id in {"IQBSR", "IQUQR"}
    bg = city["Baghdad"]
    assert nearest_hubs(ds, bg.lat, bg.lon, "air", 1)[0].id == "air:BGW"
    shz = city["Shenzhen"]
    assert nearest_hubs(ds, shz.lat, shz.lon, "sea", 1)[0].id in {"CNSZX", "CNYTN", "HKHKG"}


def test_distances():
    a, b = city["Baghdad"], city["Basra"]
    road = compute_distance(ds, a.lat, a.lon, b.lat, b.lon, "road")
    assert 450 <= road.distance_km <= 650 and road.road_factor == 1.3
    air = compute_distance(ds, a.lat, a.lon, b.lat, b.lon, "air")
    assert 400 < air.distance_km < 450
    assert road.distance_km > air.distance_km


def test_sea_lanes():
    sh = ds.hubs and next(h for h in ds.hubs if h.id == "CNSHA").point
    uq = next(h for h in ds.hubs if h.id == "IQUQR").point
    s = compute_distance(ds, sh.lat, sh.lon, uq.lat, uq.lon, "sea")
    assert 10500 < s.distance_km < 13500  # real ~ 11,500-12,000 km via Malacca
    assert "Malacca Strait" in s.via and "Strait of Hormuz" in s.via
    rt = next(h for h in ds.hubs if h.id == "NLRTM").point
    e = compute_distance(ds, sh.lat, sh.lon, rt.lat, rt.lon, "sea")
    assert 18000 < e.distance_km < 23500 and "Gulf of Suez" in e.via  # real ~ 19,500 km
    me = next(h for h in ds.hubs if h.id == "TRMER").point
    m = compute_distance(ds, sh.lat, sh.lon, me.lat, me.lon, "sea")
    assert 13000 < m.distance_km < 17500 and "Gulf of Suez" in m.via
    ny = next(h for h in ds.hubs if h.id == "USNYC").point
    ja = next(h for h in ds.hubs if h.id == "AEJEA").point
    u = compute_distance(ds, ny.lat, ny.lon, ja.lat, ja.lon, "sea")
    assert 13000 < u.distance_km < 17500 and "Strait of Gibraltar" in u.via
