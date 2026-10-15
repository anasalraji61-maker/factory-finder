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
    assert search_cities(ds, "ba")[0].name_en.lower().startswith("ba")
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


def _top(q, cc=None):
    r = search_cities(ds, q, cc)
    return r[0].name_en if r else None


def test_normalize_extended():
    assert normalize("Xi'an") == normalize("Xian") == "xian"
    assert normalize("Düsseldorf") == normalize("Dusseldorf")
    assert normalize("Saint-Etienne") == normalize("saint etienne")
    assert normalize("شنغهاى") == normalize("شنغهاي")  # ى/ي
    assert normalize("هولير") == "هولير"
    assert normalize("کرج") == normalize("كرج")  # Persian kaf


def test_search_aliases_and_old_names():
    for q, want in [("Hewler", "Erbil"), ("Canton", "Guangzhou"), ("Bombay", "Mumbai"), ("Saigon", "Ho Chi Minh City"),
                    ("Kiev", "Kyiv"), ("Tsingtao", "Qingdao"), ("Peking", "Beijing"), ("Calcutta", "Kolkata"),
                    ("Izmit", "Kocaeli"), ("Koln", "Cologne"), ("Makkah", "Mecca"), ("Dohuk", "Duhok"),
                    ("Sulaimani", "Sulaymaniyah"), ("كانتون", "Guangzhou"), ("ذي قار", "Nasiriyah"),
                    ("بابل", "Hillah"), ("Xi'an", "Xi'an"), ("Habur", "Silopi")]:
        assert _top(q) == want, q


def test_search_arabic_normalisation_and_article():
    assert _top("اسطنبول") == _top("استنبول") == "Istanbul"
    assert _top("البصره") == _top("البصرة") == _top("بصره") == "Basra"
    assert _top("الحله") == "Hillah"
    assert _top("أربيل") == _top("اربيل") == _top("إربيل") == "Erbil"
    assert _top("ابوظبي") == "Abu Dhabi"


def test_search_typos():
    for q, want in [("bagdhad", "Baghdad"), ("shangahi", "Shanghai"), ("dubay", "Dubai"), ("Guangzhuo", "Guangzhou"),
                    ("Shenzen", "Shenzhen"), ("istanbl", "Istanbul")]:
        assert _top(q) == want, q
    assert search_cities(ds, "qqqzzzx") == []  # gibberish still returns nothing
    assert search_cities(ds, "baghdd", "CN") == []  # country filter respected for fuzzy hits


def test_search_ranking_order():
    names = [c.name_en for c in search_cities(ds, "tangier")]
    assert names[0] == "Tangier"
    r = search_cities(ds, "ba")  # short query: only name/word prefixes, no mid-word substring noise
    assert r
    for c in r:
        names = [normalize(x) for x in [c.name_en, c.name_ar, *ds.aliases.get(c.id, [])]]
        assert any(w.startswith("ba") for n in names for w in n.split()), c.name_en
    assert search_cities(ds, "yiwu")[0].name_en == "Yiwu"
    assert [c.name_en for c in search_cities(ds, "iraq")] == []
