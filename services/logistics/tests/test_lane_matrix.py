"""Lane/route coverage matrix: origin x destination x mode sanity (mock geo + mock FX, no network)."""
from decimal import Decimal as D

import pytest

from ff_logistics.domain.engine import DATA, ESTIMATE_AS_OF
from ff_logistics.testing import req

ORIGINS = [("CN", "Shanghai"), ("CN", "Guangzhou"), ("US", "Chicago"), ("DE", "Hamburg"), ("TR", "Istanbul")]
DESTS = [("IQ", "Baghdad"), ("IQ", "Basra"), ("IQ", "Erbil"), ("AE", "Dubai"), ("SA", "Riyadh"), ("KW", "Kuwait City"),
         ("QA", "Doha"), ("OM", "Muscat"), ("BH", "Manama"), ("TR", "Ankara"), ("JO", "Amman"), ("JO", "Aqaba"),
         ("EG", "Cairo"), ("DE", "Munich"), ("NL", "Rotterdam"), ("FR", "Paris"), ("IT", "Milan"), ("ES", "Madrid"),
         ("GB", "London"), ("PL", "Warsaw"), ("US", "Houston"), ("US", "Chicago")]
PAIRS = [(o, d) for o in ORIGINS for d in DESTS if o[0] != d[0]]
MODES = ["sea_lcl", "sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc", "air", "rail", "road"]
ID = [f"{o[0]}-{o[1]}>{d[0]}-{d[1]}" for o, d in PAIRS]


def post(client, body):
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def check_option(o, cur):
    amounts = [D(ln["amount"]["amount"]) for ln in o["lines"]]
    total = sum(amounts)
    assert total > 0 and all(a >= 0 for a in amounts)
    lo, hi = D(o["total"]["min"]["amount"]), D(o["total"]["max"]["amount"])
    assert 0 < lo <= total <= hi, (o["mode"], lo, total, hi)
    assert o["total"]["min"]["currency"] == o["total"]["max"]["currency"] == cur
    t = o["transit_days"]
    assert 0 < t["min"] <= t["max"]
    for ln in o["lines"]:
        assert ln["amount"]["currency"] == cur and ln["source"] and ln["as_of"] and ln["fx_rate"]
        if ln["estimate"]:
            rg = ln["range"]
            assert D(rg["min"]["amount"]) <= D(ln["amount"]["amount"]) <= D(rg["max"]["amount"])
    est = [w for w in o["warnings"] if w.startswith("Estimate, confidence ")]
    assert len(est) == 1 and f"as of {ESTIMATE_AS_OF}" in est[0]
    conf = est[0].split("confidence ")[1].split(",")[0]
    assert conf in {"low", "medium"}  # never high
    return total


@pytest.mark.parametrize("o,d", PAIRS, ids=ID)
def test_matrix_default_modes(client, o, d):
    q = post(client, req(origin=o, dest=d))
    assert q["options"], "at least one feasible option"
    assert sum(1 for x in q["options"] if x["recommended"]) == 1
    assert any("approximate table" in a for a in q["assumptions"])
    modes = [x["mode"] for x in q["options"]]
    assert len(modes) == len(set(modes))
    for opt in q["options"]:
        check_option(opt, "USD")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("o,d", PAIRS[::7], ids=ID[::7])
def test_matrix_each_mode_explicit(client, o, d, mode):
    r = client.post("/v1/quotes/landed-cost", json=req(origin=o, dest=d, modes=[mode], kg=900, m3=4))
    if r.status_code == 422:  # an explicitly requested mode may be infeasible (no land link / too large / no rail)
        assert r.json()["error"]["code"] == "no_feasible_option"
        return
    assert r.status_code == 200, r.text
    (opt,) = r.json()["options"]
    assert opt["mode"] == mode
    check_option(opt, "USD")


@pytest.mark.parametrize("cur,rate", [("EUR", "0.92"), ("IQD", None), ("AED", None)])
@pytest.mark.parametrize("o,d", [(("CN", "Shanghai"), ("IQ", "Erbil")), (("DE", "Hamburg"), ("TR", "Ankara")),
                                 (("US", "Chicago"), ("AE", "Dubai"))])
def test_display_currency_conversion(client, o, d, cur, rate):
    usd = post(client, req(origin=o, dest=d, modes=["sea_fcl_40"]))["options"][0]
    conv = post(client, req(origin=o, dest=d, modes=["sea_fcl_40"], display_currency=cur))
    opt = conv["options"][0]
    assert conv["currency"] == cur
    r = D(opt["lines"][0]["fx_rate"])
    if rate:
        assert r == D(rate)
    for a, b in zip(usd["lines"], opt["lines"], strict=True):
        assert b["amount"]["currency"] == cur and b["original_amount"]["currency"] == "USD"
        assert D(b["original_amount"]["amount"]) == D(a["amount"]["amount"])
        # displayed = exact USD x rate; original_amount is shown rounded to cents, so allow half a cent x rate + 1 unit
        assert abs(D(b["amount"]["amount"]) - D(b["original_amount"]["amount"]) * r) <= D("0.005") * r + 1
    assert D(opt["total"]["min"]["amount"]) <= sum(D(x["amount"]["amount"]) for x in opt["lines"]) \
        <= D(opt["total"]["max"]["amount"])


def test_iraq_destinations_use_curated_routes(client):
    for city in ("Baghdad", "Basra", "Erbil"):
        q = post(client, req(dest=("IQ", city), modes=["sea_fcl_40"]))
        o = q["options"][0]
        assert o["destination_hub"] in {"IQUQR", "TRMER", "AEJEA", "JOAQJ"}
        assert "alternatives" in o["route_summary"]
    erbil = post(client, req(dest=("IQ", "Erbil"), modes=["rail"]))["options"][0]
    assert erbil["destination_hub"] == "TRMER" and "Ibrahim Khalil" in erbil["route_summary"]
    q = post(client, req(dest=("IQ", "Baghdad"), modes=["sea_fcl_40"]))
    assert "Aqaba + truck via Trebil" in q["options"][0]["route_summary"]  # listed as an alternative


def test_jordan_aqaba_and_gulf_hubs(client):
    assert post(client, req(dest=("JO", "Amman"), modes=["sea_fcl_40"]))["options"][0]["destination_hub"] == "JOAQJ"
    hubs = {c: post(client, req(dest=(c, city), modes=["sea_fcl_40"]))["options"][0]["destination_hub"]
            for c, city in (("AE", "Dubai"), ("KW", "Kuwait City"), ("QA", "Doha"), ("BH", "Manama"), ("SA", "Dammam"))}
    assert hubs == {"AE": "AEJEA", "KW": "KWSWK", "QA": "QAHMD", "BH": "BHKBS", "SA": "SADMM"}


def test_rail_only_on_realistic_corridors(client):
    for dest in (("AE", "Dubai"), ("SA", "Riyadh"), ("JO", "Amman"), ("EG", "Cairo")):
        r = client.post("/v1/quotes/landed-cost", json=req(dest=dest, modes=["rail"]))
        assert r.status_code == 422
        q = post(client, req(dest=dest))
        assert "rail" not in {x["mode"] for x in q["options"]}
        assert any("rail not offered" in a for a in q["assumptions"])
    q = post(client, req(dest=("DE", "Munich")))
    rail = next(x for x in q["options"] if x["mode"] == "rail")
    assert rail["destination_hub"] == "DEDUI" and "rail" in rail["route_summary"]


def test_long_and_implausible_road_not_offered_by_default(client):
    q = post(client, req(dest=("DE", "Munich")))
    assert "road" not in {x["mode"] for x in q["options"]}
    assert any("road not offered" in a for a in q["assumptions"])
    q = post(client, req(dest=("DE", "Munich"), modes=["road"]))
    assert q["options"][0]["mode"] == "road"
    assert client.post("/v1/quotes/landed-cost", json=req(origin=("DE", "Hamburg"), dest=("EG", "Cairo"),
                                                           modes=["road"])).status_code == 422
    # realistic neighbours keep road
    q = post(client, req(origin=("TR", "Istanbul"), dest=("IQ", "Erbil")))
    assert "road" in {x["mode"] for x in q["options"]}


def test_curated_sea_routes_do_not_add_neighbour_ports():
    for hub in {a["hub"] for a in DATA.routes["sea"]["IQ"]}:
        assert hub in {"IQUQR", "TRMER", "AEJEA", "JOAQJ"}


def test_data_files_carry_estimate_labels_never_high():
    for name in ("lanes", "routes"):
        blob = getattr(DATA, name)
        assert blob["confidence"] in {"low", "medium"} and blob["as_of"] == ESTIMATE_AS_OF
    assert DATA.lanes["label"].startswith("indicative estimate")
    for lane in DATA.lanes["lanes"].values():
        lo, hi = lane["sea_days"]
        assert 0 < lo < hi and lane["fcl_20"] < lane["fcl_40"] <= lane["fcl_40hc"]
        assert lane["air_days"][0] < lane["air_days"][1]
        if lane["rail_40"]:
            assert lane["rail_days"][0] < lane["rail_days"][1]
    for cc, r in DATA.lanes["regions"].items():
        assert cc in DATA.lanes["continents"] and r in DATA.handling["origin"] and r in DATA.handling["destination"]
