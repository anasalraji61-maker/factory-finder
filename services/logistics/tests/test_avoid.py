"""avoid: sea chokepoint avoidance changes sea distance/cost/time; impossible routes degrade to a note."""
import asyncio
from decimal import Decimal

from ff_logistics.clients.geo import CachedGeo, MockGeo, Point
from ff_logistics.testing import req as base_req


def post(client, **kw):
    r = client.post("/v1/quotes/landed-cost", json=base_req(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def sea40(q):
    return next(o for o in q["options"] if o["mode"] == "sea_fcl_40")


def test_avoid_increases_sea_days_and_cost(client):
    a = post(client, modes=["sea_fcl_40"])
    b = post(client, modes=["sea_fcl_40"], avoid=["suez", "bab_el_mandeb"])
    ma = next(ln for ln in sea40(a)["lines"] if ln["stage"] == "main_leg")
    mb = next(ln for ln in sea40(b)["lines"] if ln["stage"] == "main_leg")
    assert Decimal(mb["amount"]["amount"]) > Decimal(ma["amount"]["amount"])
    assert sea40(b)["transit_days"]["max"] > sea40(a)["transit_days"]["max"]
    assert any("Avoiding bab_el_mandeb, suez" in n and "estimate" in n for n in b["assumptions"])
    assert not any("Avoiding" in n for n in a["assumptions"])


def test_avoid_does_not_touch_air(client):
    a = post(client, modes=["air"], kg=300, m3=2)
    b = post(client, modes=["air"], kg=300, m3=2, avoid=["suez"])
    assert a["options"][0]["total"] == b["options"][0]["total"]


def test_avoid_unknown_value_rejected(client):
    assert client.post("/v1/quotes/landed-cost", json=base_req(avoid=["nope"])).status_code == 422


def test_hormuz_impossible_gives_note_not_failure(client):
    q = post(client, modes=["sea_fcl_40"], dest=("IQ", "Basra"), avoid=["hormuz"])
    assert sea40(q)
    assert any("no sea route exists while avoiding hormuz" in n and "NOT applied" in n for n in q["assumptions"])


def test_mock_geo_and_cache_key_include_avoid():
    a, b = Point(31.2, 121.5), Point(51.9, 4.1)
    g = CachedGeo(MockGeo())
    plain = asyncio.run(g.distance_km(a, b, "sea"))
    avoided = asyncio.run(g.distance_km(a, b, "sea", avoid=("suez",)))
    again = asyncio.run(g.distance_km(a, b, "sea", avoid=("suez",)))
    assert avoided > plain and again == avoided and g.misses == 2 and g.hits == 1
