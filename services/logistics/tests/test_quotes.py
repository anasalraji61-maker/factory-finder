from decimal import Decimal as D

import pytest

from ff_logistics.testing import req


def post(client, body):
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def mode(q, m):
    return next(o for o in q["options"] if o["mode"] == m)


def lsum(o):
    return sum(D(ln["amount"]["amount"]) for ln in o["lines"])


def check_totals(q):
    for o in q["options"]:
        tmin, tmax = D(o["total"]["min"]["amount"]), D(o["total"]["max"]["amount"])
        assert (tmin + tmax) / 2 == lsum(o)  # total mid == sum of lines
        assert tmin <= tmax
        assert all(ln["source"] and isinstance(ln["estimate"], bool) for ln in o["lines"])
    totals = [(D(o["total"]["min"]["amount"]) + D(o["total"]["max"]["amount"])) / 2 for o in q["options"]]
    assert sum(o["recommended"] for o in q["options"]) == 1
    assert [o["lines"][0]["stage"] for o in q["options"]] == ["goods"] * len(totals)


def stages(o):
    return [ln["stage"] for ln in o["lines"]]


def test_golden_shanghai_baghdad_fcl(client):
    q = post(client, req())
    check_totals(q)
    o = mode(q, "sea_fcl_40hc")
    assert o["origin_hub"] in {"CNSHA", "CNNGB"} and o["destination_hub"] == "IQUQR"
    assert "Mersin" in o["route_summary"] and 30 <= o["transit_days"]["min"] <= 40
    assert stages(o) == ["goods", "origin_inland", "origin_handling", "main_leg", "insurance",
                         "destination_handling", "duties", "taxes", "clearance", "destination_inland"]
    assert o["co2_kg"] > 0 and any("table" in a for a in q["assumptions"])


def test_golden_yiwu_lcl_erbil_via_mersin(client):
    q = post(client, req(origin=("CN", "Yiwu"), dest=("IQ", "Erbil"), kg=2500, m3=6, value="9000"))
    check_totals(q)
    o = mode(q, "sea_lcl")
    assert o["destination_hub"] == "TRMER" and "Ibrahim Khalil" in o["route_summary"]
    assert any(ln["stage"] == "main_leg" and "LCL 6.00 W/M" in ln["description"] for ln in o["lines"])
    assert "sea_fcl_40" not in {x["mode"] for x in q["options"]}  # too small for FCL 40


def test_golden_guangzhou_air_baghdad(client):
    q = post(client, req(origin=("CN", "Guangzhou"), kg=300, m3=2, value="60000", modes=["air"]))
    o = q["options"][0]
    assert o["mode"] == "air" and o["destination_hub"] == "BGW" and o["transit_days"]["max"] <= 25
    assert "chargeable" in next(ln for ln in o["lines"] if ln["stage"] == "main_leg")["description"]
    check_totals(q)


def test_golden_hamburg_basra_and_ningbo_istanbul(client):
    q = post(client, req(origin=("DE", "Hamburg"), dest=("IQ", "Basra"), kg=9000, m3=25))
    check_totals(q)
    assert mode(q, "sea_fcl_40")["origin_hub"] == "DEHAM" and mode(q, "sea_fcl_40")["destination_hub"] == "IQUQR"
    q = post(client, req(origin=("CN", "Ningbo"), dest=("TR", "Istanbul"), kg=12000, m3=30))
    check_totals(q)
    assert mode(q, "sea_fcl_20")["origin_hub"] == "CNNGB" and mode(q, "sea_fcl_20")["destination_hub"] == "TRIST"


def test_sorted_by_total_and_recommended_rule(client):
    q = post(client, req(origin=("CN", "Guangzhou"), kg=800, m3=5, value="100000"))
    tot = [D(o["total"]["min"]["amount"]) + D(o["total"]["max"]["amount"]) for o in q["options"]]
    assert tot == sorted(tot)
    rec = next(o for o in q["options"] if o["recommended"])
    assert rec["mode"] in {"air", "sea_lcl"}


def test_every_mode_can_be_requested(client):
    q = post(client, req(kg=20000, m3=50, modes=["sea_lcl", "sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc",
                                                  "air", "rail", "road"]))
    assert {o["mode"] for o in q["options"]} >= {"sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc", "rail", "road"}
    check_totals(q)


@pytest.mark.parametrize("inc,present,absent", [
    ("EXW", {"origin_inland", "origin_handling", "main_leg", "insurance"}, set()),
    ("FCA", {"origin_handling", "main_leg"}, {"origin_inland"}),
    ("FOB", {"main_leg", "insurance"}, {"origin_inland", "origin_handling"}),
    ("CFR", {"insurance", "destination_handling"}, {"main_leg"}),
    ("CIF", {"destination_handling", "duties"}, {"main_leg", "insurance"}),
    ("DAP", {"duties", "taxes", "clearance"}, {"destination_handling", "destination_inland", "main_leg"}),
    ("DDP", set(), {"duties", "taxes", "clearance", "main_leg", "destination_inland"}),
])
def test_incoterm_stage_inclusion(client, inc, present, absent):
    q = post(client, req(inc=inc, modes=["sea_fcl_40hc"]))
    s = set(stages(q["options"][0]))
    assert present <= s and not (absent & s)
    check_totals(q)
    if inc == "DDP":
        assert s == {"goods"} and D(q["options"][0]["total"]["min"]["amount"]) == D("40000")


def test_insurance_flag_and_exw_costs_more_than_fob(client):
    exw = post(client, req(inc="EXW", insurance=False, modes=["sea_fcl_40hc"]))["options"][0]
    fob = post(client, req(inc="FOB", insurance=False, modes=["sea_fcl_40hc"]))["options"][0]
    assert "insurance" not in stages(exw) and lsum(exw) > lsum(fob)


def test_customs_value_includes_freight_for_fob_not_cif(client):
    def duty(inc):
        o = post(client, req(inc=inc, modes=["sea_fcl_40hc"]))["options"][0]
        return D(next(ln for ln in o["lines"] if ln["stage"] == "duties")["amount"]["amount"])
    assert duty("FOB") > duty("CIF") == D("2000.00")  # 5% (IQ ch.84) of 40000


def test_display_currency_and_unit_price(client):
    body = req(modes=["sea_fcl_40hc"], display_currency="IQD")
    body["goods"].pop("total_value")
    body["goods"]["unit_price"] = {"amount": "40", "currency": "USD"}  # x quantity 1000
    q = post(client, body)
    assert q["currency"] == "IQD"
    g = q["options"][0]["lines"][0]
    assert g["amount"]["amount"] == str(40000 * 1310) and g["original_amount"]["amount"] == "40000.00"
    check_totals(q)


def test_warnings(client):
    q = post(client, req(dest=("IR", "Tehran"), modes=["sea_fcl_40hc"]))
    assert any("IR" in w for w in q["warnings"]) and any("Sanctions" in w for w in q["options"][0]["warnings"])
    b = req(origin=("CN", "Guangzhou"), kg=200, m3=1, modes=["air"])
    b["goods"]["dangerous_goods"] = True
    q = post(client, b)
    assert any("Dangerous goods by air" in w for w in q["options"][0]["warnings"])
    q = post(client, req(kg=14000, m3=20, modes=["sea_lcl"], value="300"))
    w = " ".join(q["options"][0]["warnings"])
    assert "LCL" in w and "Very low" in w and "% of the goods value" in w
    q = post(client, req(origin=("CN", "Guangzhou"), kg=100, m3=25, modes=["air"]))
    assert any("bulky" in w for w in q["options"][0]["warnings"])


def test_errors(client):
    r = client.post("/v1/quotes/landed-cost", json={"goods": {}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    b = req()
    b["goods"].pop("total_value")
    assert client.post("/v1/quotes/landed-cost", json=b).json()["error"]["code"] == "goods_value_required"
    r = client.post("/v1/quotes/landed-cost", json=req(origin=("CN", "Atlantis"), modes=["road"]))
    assert r.status_code == 200  # unknown city falls back to country default
    r = client.post("/v1/quotes/landed-cost", json=req(origin=("ZZ", "Nowhere")))
    assert r.json()["error"]["code"] == "location_unresolved"
    r = client.post("/v1/quotes/landed-cost", json=req(origin=("US", "Los Angeles"), modes=["road"], dest=("IQ", "Baghdad")))
    assert r.json()["error"]["code"] == "no_feasible_option"


def test_other_endpoints(client):
    assert client.get("/health").json() == {"status": "ok", "service": "logistics", "version": "0.1.0"}
    rates = client.get("/v1/fx/rates?base=USD").json()
    assert rates["rates"]["IQD"] == "1310" and rates["source"] == "mock"
    c = client.post("/v1/fx/convert", json={"amount": "100", "from": "USD", "to": "IQD"}).json()
    assert c["amount"] == {"amount": "131000", "currency": "IQD"}
    assert client.post("/v1/fx/convert", json={"amount": "1", "from": "USD", "to": "XXX"}).status_code == 400
    cs = client.get("/v1/carriers").json()
    assert cs["total"] >= 25
    cs = client.get("/v1/carriers?origin_country=CN&destination_country=IQ&mode=air").json()
    assert cs["items"] and all("air" in c["modes"] for c in cs["items"])


def test_internal_token_enforced_when_set():
    from fastapi.testclient import TestClient

    from ff_logistics.config import Settings
    from ff_logistics.main import create_app
    c = TestClient(create_app(Settings(internal_token="s3", geo_provider="mock")))
    assert c.get("/v1/carriers").status_code == 401
    assert c.get("/v1/carriers", headers={"X-Internal-Token": "s3"}).status_code == 200
    # a non-ASCII token must be a clean 401, not a TypeError from hmac.compare_digest(str, str)
    assert c.get("/v1/carriers", headers={"X-Internal-Token": "é".encode("latin-1")}).status_code == 401
    assert c.get("/health").status_code == 200


def test_geo_down_returns_502():
    from fastapi.testclient import TestClient

    from ff_logistics.config import Settings
    from ff_logistics.main import create_app
    c = TestClient(create_app(Settings(geo_provider="http", geo_url="http://127.0.0.1:1")))
    r = c.post("/v1/quotes/landed-cost", json=req())
    assert r.status_code == 502 and r.json()["error"]["code"] == "geo_unavailable"
