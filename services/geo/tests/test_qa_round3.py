"""QA round 3 (geo): landlocked hinterlands, Umm Qasr/Basra, chokepoint detours, ambiguous city names."""
import pytest
from fastapi.testclient import TestClient

from ff_geo.main import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


@pytest.fixture(scope="module")
def hubs(client):
    return {h["id"]: h for h in client.get("/v1/hubs").json()["items"]}


def city(client, q, country=None):
    params = {"q": q, **({"country": country} if country else {})}
    return client.get("/v1/cities", params=params).json()["items"]


def nearest(client, p, **kw):
    return client.get("/v1/hubs/nearest", params={"lat": p["lat"], "lon": p["lon"], **kw}).json()["items"]


# ---------------------------------------------------------------- landlocked
LANDLOCKED = [("Erbil", "IQ", None), ("Kabul", "AF", "PKKHI"), ("Addis Ababa", "ET", "DJJIB"),
              ("Kampala", "UG", "KEMBA"), ("Vienna", "AT", None)]


@pytest.mark.parametrize("name,cc,port", LANDLOCKED)
def test_landlocked_city_resolves_and_has_a_serving_port_in_another_country(client, name, cc, port):
    c = next(x for x in city(client, name, cc) if x["name_en"] == name)
    assert c["country_code"] == cc
    served = nearest(client, c["point"], type="sea", limit=3, country=cc)
    assert served, f"no sea hub serves {cc}"
    best = served[0]
    assert best["country_code"] != cc or cc == "IQ"  # landlocked: the gateway is abroad (Iraq has its own coast)
    assert best["distance_km"] > 300 or cc == "IQ"
    if port:
        assert best["id"] == port
    assert [h["distance_km"] for h in served] == sorted(h["distance_km"] for h in served)


def test_landlocked_countries_have_an_airport_for_air_freight(client, hubs):
    for iata, cc in [("KBL", "AF"), ("ADD", "ET"), ("EBB", "UG")]:
        h = hubs[f"air:{iata}"]
        assert h["country_code"] == cc and h["iata"] == iata
    assert {"AF", "ET", "UG"} <= {x["iso2"] for x in client.get("/v1/countries").json()["items"]}


def test_umm_qasr_is_iraqs_main_port_and_basra_is_close(client, hubs):
    iq_sea = client.get("/v1/hubs", params={"country": "IQ", "type": "sea"}).json()["items"]
    assert "IQUQR" in {h["id"] for h in iq_sea}
    basra = next(x for x in city(client, "Basra", "IQ"))
    near = nearest(client, basra["point"], type="sea", limit=3, country="IQ")
    umm = next(h for h in near if h["id"] == "IQUQR")
    assert umm["distance_km"] < 80  # Basra is a short haul from Umm Qasr
    r = client.get("/v1/distance", params={"from_lat": umm["point"]["lat"], "from_lon": umm["point"]["lon"],
                                           "to_lat": basra["point"]["lat"], "to_lon": basra["point"]["lon"],
                                           "mode": "road", "country": "IQ"}).json()
    assert r["distance_km"] < 120
    baghdad = next(x for x in city(client, "Baghdad", "IQ"))
    r2 = client.get("/v1/distance", params={"from_lat": umm["point"]["lat"], "from_lon": umm["point"]["lon"],
                                            "to_lat": baghdad["point"]["lat"], "to_lon": baghdad["point"]["lon"],
                                            "mode": "road", "country": "IQ"}).json()
    assert r2["distance_km"] > 4 * r["distance_km"]


# ---------------------------------------------------------------- chokepoints
def sea(client, a, b, **kw):
    return client.get("/v1/distance", params={"from_lat": a["lat"], "from_lon": a["lon"], "to_lat": b["lat"],
                                              "to_lon": b["lon"], "mode": "sea", **kw})


@pytest.mark.parametrize("dst,choke", [("NLRTM", "suez"), ("NLRTM", "bab_el_mandeb"), ("GRPIR", "suez"),
                                       ("GRPIR", "bab_el_mandeb"), ("AEJEA", "suez"), ("SAJED", "bab_el_mandeb"),
                                       ("DJJIB", "bab_el_mandeb")])
def test_avoiding_a_chokepoint_adds_distance_and_time(client, hubs, dst, choke):
    a, b = hubs["CNSHA"]["point"], hubs[dst]["point"]
    base = sea(client, a, b).json()
    r = sea(client, a, b, avoid=choke).json()
    assert r["avoided"] == [choke] and r["distance_km"] > base["distance_km"]
    assert r["duration_hours"] > base["duration_hours"]
    assert r["via"] != base["via"]


def test_suez_detour_to_europe_is_long_and_leaves_the_canal(client, hubs):
    a, b = hubs["CNSHA"]["point"], hubs["NLRTM"]["point"]
    base, r = sea(client, a, b).json(), sea(client, a, b, avoid="suez").json()
    extra = r["distance_km"] - base["distance_km"]
    assert 3000 < extra < 9000  # ~ +25-45% (Cape or Panama alternative: both are comparable on this graph)
    assert "Port Said" in base["via"] and "Port Said" not in r["via"] and "Gulf of Suez" not in r["via"]


def test_hormuz_avoidance_closes_gulf_ports_but_not_the_rest(client, hubs):
    a = hubs["CNSHA"]["point"]
    for gulf in ("IQUQR", "KWSWK"):
        if gulf in hubs:
            r = sea(client, a, hubs[gulf]["point"], avoid="hormuz")
            assert r.status_code == 422 and r.json()["error"]["code"] == "sea_route_unavailable"
    b = hubs["NLRTM"]["point"]
    base, r = sea(client, a, b).json(), sea(client, a, b, avoid="hormuz").json()
    assert r["distance_km"] >= base["distance_km"]


def test_avoiding_everything_relevant_never_shortens_any_route(client, hubs):
    pairs = [("CNSHA", d) for d in ("NLRTM", "GRPIR", "AEJEA", "SAJED", "INNSA", "KEMBA", "USLAX")
             if d in hubs]
    for src, dst in pairs:
        base = sea(client, hubs[src]["point"], hubs[dst]["point"]).json()["distance_km"]
        for choke in ("suez", "hormuz", "bab_el_mandeb"):
            r = sea(client, hubs[src]["point"], hubs[dst]["point"], avoid=choke)
            if r.status_code == 200:
                assert r.json()["distance_km"] >= base - 0.01, (dst, choke)


def test_avoid_multiple_chokepoints_costs_at_least_as_much_as_one(client, hubs):
    a, b = hubs["CNSHA"]["point"], hubs["GRPIR"]["point"]
    one = sea(client, a, b, avoid="suez").json()["distance_km"]
    both = sea(client, a, b, avoid="suez,bab_el_mandeb").json()["distance_km"]
    assert both >= one


# ---------------------------------------------------------------- ambiguous names
@pytest.mark.parametrize("q,min_places,countries", [
    ("Springfield", 3, {"US"}), ("Alexandria", 3, {"EG", "US", "RO"}), ("Victoria", 2, {"CA", "MX"})])
def test_ambiguous_names_return_every_candidate_with_its_country(client, q, min_places, countries):
    items = city(client, q)
    assert len(items) >= min_places
    assert {c["country_code"] for c in items} >= countries
    ids = [c["id"] for c in items]
    assert len(set(ids)) == len(ids)  # each candidate is individually addressable
    assert all({"id", "name_en", "name_ar", "country_code", "point"} <= set(c) for c in items)
    pts = [(c["point"]["lat"], c["point"]["lon"]) for c in items]
    assert len(set(pts)) == len(pts)


def test_country_filter_disambiguates_across_countries_not_within(client):
    assert [c["country_code"] for c in city(client, "Alexandria", "EG")] == ["EG"]
    assert [c["country_code"] for c in city(client, "Alexandria", "US")] == ["US"]
    assert len(city(client, "Springfield", "US")) == 3  # same-country homonyms stay listed, ids tell them apart
    assert city(client, "Springfield", "DE") == []


def test_exact_name_ranks_before_partial_and_is_deterministic(client):
    first = [c["id"] for c in city(client, "Victoria")]
    assert first == [c["id"] for c in city(client, "Victoria")]
    assert first[0] == "CA-VICTORIA" or first[0] == "MX-CIUDAD_VICTORIA"
