import pytest
from fastapi.testclient import TestClient

from ff_geo.main import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "service": "geo", "version": "0.1.0"}


def test_countries(client):
    r = client.get("/v1/countries").json()
    assert r["total"] >= 45 and {"iso2", "name_ar", "road_factor"} <= set(r["items"][0])


def test_cities(client):
    r = client.get("/v1/cities", params={"q": "بغداد", "country": "IQ"}).json()
    assert r["items"][0]["name_en"] == "Baghdad"
    assert client.get("/v1/cities", params={"country": "IQ", "limit": 100}).json()["total"] >= 18
    assert client.get("/v1/cities", params={"q": "zzzz"}).json() == {"items": [], "total": 0}


def test_hubs(client):
    r = client.get("/v1/hubs", params={"country": "IQ", "type": "sea"}).json()
    assert {"IQUQR", "IQBSR"} <= {h["id"] for h in r["items"]}
    land = client.get("/v1/hubs", params={"type": "land"}).json()["items"]
    assert land and all(h["type"] == "land_border" for h in land)
    # hubs serving Iraq from outside it
    ids = {h["id"] for h in client.get("/v1/hubs", params={"country": "IQ", "type": "sea"}).json()["items"]}
    assert "TRMER" in ids


def test_nearest(client):
    r = client.get("/v1/hubs/nearest", params={"lat": 31.23, "lon": 121.47, "type": "sea", "limit": 2})
    items = r.json()["items"]
    assert items[0]["id"] == "CNSHA" and len(items) == 2
    assert items[0]["distance_km"] <= items[1]["distance_km"]


def test_distance(client):
    p = {"from_lat": 33.3152, "from_lon": 44.3661, "to_lat": 30.5085, "to_lon": 47.7835}
    r = client.get("/v1/distance", params={**p, "mode": "road"}).json()
    assert 450 <= r["distance_km"] <= 650
    s = client.get("/v1/distance", params={**p, "mode": "sea"})
    assert s.status_code == 200


def test_errors(client):
    r = client.get("/v1/hubs", params={"country": "ZZ"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "country_not_found"
    r = client.get("/v1/hubs/nearest", params={"lat": 100, "lon": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.get("/v1/hubs", params={"type": "bogus"})
    assert r.status_code == 422
    assert client.get("/v1/nope").json()["error"]["code"] == "not_found"
