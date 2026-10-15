"""QA round 3: landlocked destinations, transit monotonicity, Umm Qasr/Basra, incoterm x mode line table,
currency minor units, dangerous goods, extreme cargo sizes, ambiguous city names. Mock geo + mock FX only."""
import re
from decimal import Decimal as D

import pytest

from ff_logistics.clients.geo import MockGeo
from ff_logistics.domain.money import money, quantize
from ff_logistics.testing import req

SEA_HUBS = {h.id for h in MockGeo()._hubs if h.type == "sea"}
SEA_MODES = ["sea_lcl", "sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc"]


def post(client, body):
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def line(opt, stage):
    return next((ln for ln in opt["lines"] if ln["stage"] == stage), None)


def amt(opt, stage):
    ln = line(opt, stage)
    return D(ln["amount"]["amount"]) if ln else None


def km_of(desc):
    return int(re.search(r"\((\d+) km\)", desc).group(1))


# ------------------------------------------------------------------ landlocked destinations
LANDLOCKED = [(("IQ", "Erbil"), {"TRMER"}), (("AF", "Kabul"), {"PKKHI"}), (("ET", "Addis Ababa"), {"DJJIB"}),
              (("UG", "Kampala"), {"KEMBA"}), (("AT", "Vienna"), None)]


@pytest.mark.parametrize("dest,ports", LANDLOCKED, ids=[d[0][1] for d in LANDLOCKED])
def test_landlocked_destination_routes_via_foreign_port_plus_inland_haul(client, dest, ports):
    q = post(client, req(dest=dest, modes=["sea_fcl_40", "sea_fcl_40hc"]))
    assert q["options"]
    for o in q["options"]:
        hub = o["destination_hub"]
        assert hub in SEA_HUBS and (ports is None or hub in ports), o["route_summary"]
        inland = line(o, "destination_inland")
        assert D(inland["amount"]["amount"]) > 0 and "Truck" in inland["description"]
        assert km_of(inland["description"]) >= 300, inland["description"]  # a real overland haul
        assert amt(o, "main_leg") > 0 and amt(o, "destination_handling") > 0
        assert o["transit_days"]["min"] >= 20  # sea leg + inland + clearance, never a day-trip


def test_landlocked_foreign_port_adds_border_cost_vs_coastal_peer(client):
    """Same cargo, same port-to-door distance class: crossing a border costs more than a domestic haul."""
    kampala = post(client, req(dest=("UG", "Kampala"), modes=["sea_fcl_40"]))["options"][0]
    inland = D(line(kampala, "destination_inland")["amount"]["amount"])
    km = km_of(line(kampala, "destination_inland")["description"])
    domestic = post(client, req(dest=("KE", "Nairobi"), modes=["sea_fcl_40"]))["options"][0]
    d_inland = D(line(domestic, "destination_inland")["amount"]["amount"])
    d_km = km_of(line(domestic, "destination_inland")["description"])
    assert inland / km > d_inland / d_km  # per-km includes the 250 USD border fee


# ------------------------------------------------------------------ Umm Qasr / Basra
def test_umm_qasr_is_the_main_iraqi_port_and_basra_inland_is_small(client):
    q = post(client, req(dest=("IQ", "Basra"), modes=["sea_fcl_40", "sea_fcl_40hc", "sea_fcl_20"]))
    for o in q["options"]:
        assert o["destination_hub"] == "IQUQR"
        inland = line(o, "destination_inland")
        assert km_of(inland["description"]) < 120
        assert amt(o, "destination_inland") < amt(o, "main_leg") / 5  # trucking is a small fraction of the ocean leg
    baghdad = post(client, req(dest=("IQ", "Baghdad"), modes=["sea_fcl_40"]))["options"][0]
    basra40 = next(o for o in q["options"] if o["mode"] == "sea_fcl_40")
    assert baghdad["destination_hub"] == "IQUQR"
    assert amt(basra40, "destination_inland") < amt(baghdad, "destination_inland")


# ------------------------------------------------------------------ transit time monotonic with distance
def test_road_transit_is_monotonic_in_distance_within_a_country(client):
    rows = []
    for city in ["Chicago", "Atlanta", "New York", "Savannah", "Houston", "Los Angeles"]:
        o = post(client, req(origin=("US", "Chicago"), dest=("US", city), modes=["road"], kg=5000, m3=20))["options"][0]
        km = int(re.search(r"truck (\d+) km", line(o, "main_leg")["description"]).group(1))
        rows.append((km, o["transit_days"]["min"], o["transit_days"]["max"]))
    rows.sort()
    assert rows[0][0] == 0 and rows[-1][0] > 3000
    for a, b in zip(rows, rows[1:], strict=False):
        assert b[1] >= a[1] and b[2] >= a[2], (a, b)
    assert rows[-1][2] > rows[0][2]


def test_sea_transit_grows_with_inland_distance_from_the_same_port(client):
    rows = []
    for city in ["Basra", "Najaf", "Baghdad"]:
        o = post(client, req(dest=("IQ", city), modes=["sea_fcl_40"]))["options"][0]
        if o["destination_hub"] == "IQUQR":
            rows.append((km_of(line(o, "destination_inland")["description"]), o["transit_days"]["min"],
                         o["transit_days"]["max"]))
    rows.sort()
    assert len(rows) >= 2
    for a, b in zip(rows, rows[1:], strict=False):
        assert b[1] >= a[1] and b[2] >= a[2], (a, b)


def test_transit_ranges_are_well_formed_everywhere(client):
    for dest in [("IQ", "Baghdad"), ("AF", "Kabul"), ("ET", "Addis Ababa"), ("US", "Houston"), ("AT", "Vienna")]:
        for o in post(client, req(dest=dest, kg=800, m3=3))["options"]:
            t = o["transit_days"]
            assert 0 < t["min"] <= t["max"], (dest, o["mode"], t)


# ------------------------------------------------------------------ incoterm x mode line inclusion (literal table)
ALL_STAGES = {"origin_inland", "origin_handling", "main_leg", "insurance", "destination_handling", "duties", "taxes",
              "clearance", "destination_inland"}
SELLER_PAYS = {  # stages the supplier price already covers
    "EXW": set(), "FCA": {"origin_inland"}, "FOB": {"origin_inland", "origin_handling"},
    "CFR": {"origin_inland", "origin_handling", "main_leg"},
    "CIF": {"origin_inland", "origin_handling", "main_leg", "insurance"},
    "DAP": ALL_STAGES - {"duties", "taxes", "clearance"}, "DDP": ALL_STAGES,
}
MODE_CASES = {  # mode -> (origin, dest, kg, m3, stages the mode builds)
    "sea_lcl": (("CN", "Shanghai"), ("IQ", "Baghdad"), 3000, 8, ALL_STAGES),
    "sea_fcl_20": (("CN", "Shanghai"), ("IQ", "Baghdad"), 18000, 20, ALL_STAGES),
    "sea_fcl_40": (("CN", "Shanghai"), ("IQ", "Baghdad"), 18000, 60, ALL_STAGES),
    "sea_fcl_40hc": (("CN", "Shanghai"), ("IQ", "Baghdad"), 18000, 60, ALL_STAGES),
    "air": (("CN", "Shanghai"), ("IQ", "Baghdad"), 400, 2, ALL_STAGES),
    "rail": (("CN", "Shanghai"), ("IQ", "Baghdad"), 18000, 60, ALL_STAGES),
    "road": (("TR", "Istanbul"), ("IQ", "Baghdad"), 12000, 40, ALL_STAGES - {"origin_inland", "destination_inland"}),
}


@pytest.mark.parametrize("insurance", [True, False])
@pytest.mark.parametrize("inc", list(SELLER_PAYS))
@pytest.mark.parametrize("mode", list(MODE_CASES))
def test_incoterm_line_inclusion_table(client, mode, inc, insurance):
    o_, d_, kg, m3, built = MODE_CASES[mode]
    q = post(client, req(origin=o_, dest=d_, kg=kg, m3=m3, inc=inc, modes=[mode], insurance=insurance))
    opt = q["options"][0]
    assert opt["mode"] == mode
    expected = built - SELLER_PAYS[inc] - (set() if insurance else {"insurance"})
    stages = [ln["stage"] for ln in opt["lines"]]
    assert stages[0] == "goods" and set(stages[1:]) == expected, (mode, inc, stages)
    assert len(stages) == len(set(stages))
    total_lo, total_hi = D(opt["total"]["min"]["amount"]), D(opt["total"]["max"]["amount"])
    assert total_lo <= sum(D(ln["amount"]["amount"]) for ln in opt["lines"]) <= total_hi


def test_customs_value_shrinks_as_seller_takes_more(client):
    duties = {}
    for inc in SELLER_PAYS:
        o = post(client, req(inc=inc, modes=["sea_fcl_40"]))["options"][0]
        duties[inc] = amt(o, "duties")
    assert duties["EXW"] > duties["FCA"] > duties["FOB"] > duties["CFR"] > duties["CIF"] > 0
    assert duties["CIF"] == duties["DAP"] and duties["DDP"] is None  # seller clears and pays under DDP


def test_ddp_total_is_goods_only(client):
    o = post(client, req(inc="DDP", modes=["sea_fcl_40"]))["options"][0]
    assert [ln["stage"] for ln in o["lines"]] == ["goods"]


# ------------------------------------------------------------------ currency minor units
def test_quantize_units():
    assert quantize(D("1234.5"), "IQD") == D("1235") and quantize(D("2.5"), "JPY") == D("3")
    assert quantize(D("1.0005"), "KWD") == D("1.001") and quantize(D("1.005"), "USD") == D("1.01")
    assert money(D("3.14159"), "KWD")["amount"] == "3.142" and money(D("7.2"), "JOD")["amount"] == "7.200"
    assert money(D("999.5"), "JPY")["amount"] == "1000"


@pytest.mark.parametrize("cur,decimals", [("IQD", 0), ("JPY", 0), ("KRW", 0), ("KWD", 3), ("JOD", 3), ("USD", 2), ("EUR", 2)])
def test_display_currency_minor_units_in_every_amount(client, cur, decimals):
    q = post(client, req(display_currency=cur, kg=500, m3=2, modes=["air", "sea_lcl"]))
    pat = re.compile(r"^\d+$" if decimals == 0 else rf"^\d+\.\d{{{decimals}}}$")
    for o in q["options"]:
        values = [ln["amount"] for ln in o["lines"]] + [o["total"]["min"], o["total"]["max"]]
        for ln in o["lines"]:
            if ln["estimate"]:
                values += [ln["range"]["min"], ln["range"]["max"]]
        for v in values:
            assert v["currency"] == cur and pat.match(v["amount"]), (cur, v)
        lo, hi = D(o["total"]["min"]["amount"]), D(o["total"]["max"]["amount"])
        assert lo <= sum(D(ln["amount"]["amount"]) for ln in o["lines"]) <= hi


def test_same_quote_in_iqd_jpy_kwd_is_consistent_with_usd(client):
    usd = post(client, req(kg=500, m3=2, modes=["air"]))["options"][0]
    base = sum(D(ln["amount"]["amount"]) for ln in usd["lines"])
    for cur, rate, tol in [("IQD", D(1310), D("0.001")), ("JPY", D(150), D("0.001")), ("KWD", D("0.307"), D("0.001"))]:
        o = post(client, req(kg=500, m3=2, modes=["air"], display_currency=cur))["options"][0]
        got = sum(D(ln["amount"]["amount"]) for ln in o["lines"])
        assert abs(got - base * rate) / (base * rate) < tol, cur


# ------------------------------------------------------------------ dangerous goods
DG_FACTOR = {"air": D("1.6"), "sea_lcl": D("1.35"), "sea_fcl_40": D("1.35"), "rail": D("1.3"), "road": D("1.2")}


@pytest.mark.parametrize("mode", list(DG_FACTOR))
def test_dangerous_goods_surcharge_applies_to_main_leg_only(client, mode):
    o_, d_, kg, m3, _ = MODE_CASES[mode]
    plain = req(origin=o_, dest=d_, kg=kg, m3=m3, modes=[mode])
    dg = req(origin=o_, dest=d_, kg=kg, m3=m3, modes=[mode])
    dg["goods"]["dangerous_goods"] = True
    a, b = post(client, plain)["options"][0], post(client, dg)["options"][0]
    ratio = amt(b, "main_leg") / amt(a, "main_leg")
    assert abs(ratio - DG_FACTOR[mode]) < D("0.005"), (mode, ratio)
    assert "DG surcharge" in line(b, "main_leg")["description"]
    for stage in ("origin_handling", "destination_handling", "clearance"):
        assert amt(a, stage) == amt(b, stage), stage
    assert any("Dangerous goods" in w for w in b["warnings"])
    assert not any("Dangerous goods" in w for w in a["warnings"])
    if mode == "air":
        assert any("IATA DGR" in w for w in b["warnings"])
    else:
        assert any("IMDG/ADR" in w for w in b["warnings"])


def test_dangerous_goods_compliance_flags_and_documents(client):
    def chk(dg, mode):
        r = client.post("/v1/compliance/checklist", json={
            "destination_country": "IQ", "origin_country": "CN", "hs_code": "850760", "mode": mode,
            "dangerous_goods": dg})
        assert r.status_code == 200, r.text
        return r.json()
    for mode in ("air", "sea_fcl_40", "road"):
        plain, dg = chk(False, mode), chk(True, mode)
        new_docs = {d["id"] for d in dg["documents"]} - {d["id"] for d in plain["documents"]}
        assert {"dangerous_goods_declaration", "safety_data_sheet"} <= new_docs
        assert dg["timeline"]["clearance_days"]["max"] > plain["timeline"]["clearance_days"]["max"]
        assert any("Dangerous goods" in a for a in dg["assumptions"])
        assert {r["id"] for r in dg["restrictions"]} >= {r["id"] for r in plain["restrictions"]}  # never fewer flags
    body = req(kg=500, m3=2, modes=["air"])
    body["goods"].update(dangerous_goods=True, hs_code="850760")
    hint = post(client, body)["compliance_hint"]
    assert hint["clearance_days"]["max"] >= chk(False, "air")["timeline"]["clearance_days"]["max"]


# ------------------------------------------------------------------ very small / very large cargo
def test_tiny_cargo_one_kg_one_litre(client):
    q = post(client, req(kg=1, m3="0.001", value="50"))
    modes = {o["mode"] for o in q["options"]}
    assert modes == {"air", "sea_lcl"}  # no FCL / rail for a parcel
    for o in q["options"]:
        assert amt(o, "main_leg") > 0 and amt(o, "insurance") > 0
        assert D(o["total"]["min"]["amount"]) > 0
        assert any("Very low goods value" in w for w in o["warnings"])
    lcl = next(o for o in q["options"] if o["mode"] == "sea_lcl")
    assert "LCL 1.00 W/M" in line(lcl, "main_leg")["description"]  # minimum 1 revenue tonne
    air = next(o for o in q["options"] if o["mode"] == "air")
    assert "Air 1 kg chargeable" in line(air, "main_leg")["description"]
    assert amt(air, "main_leg") >= 50  # minimum charge, not 1 kg * rate


def test_tiny_cargo_costs_never_exceed_larger_cargo(client):
    small = post(client, req(kg=1, m3="0.001", modes=["air"]))["options"][0]
    big = post(client, req(kg=500, m3="2", modes=["air"]))["options"][0]
    assert amt(small, "main_leg") <= amt(big, "main_leg")
    assert amt(small, "origin_inland") <= amt(big, "origin_inland")


def test_huge_cargo_60t_200m3(client):
    q = post(client, req(kg=60000, m3=200))
    modes = {o["mode"] for o in q["options"]}
    assert not modes & {"air", "sea_lcl"} and "sea_fcl_40hc" in modes
    hc = next(o for o in q["options"] if o["mode"] == "sea_fcl_40hc")
    assert "3 x 40hc' container" in line(hc, "main_leg")["description"]  # ceil(200/68)=3, ceil(60t/26t)=3
    one = post(client, req(kg=18000, m3=60, modes=["sea_fcl_40hc"]))["options"][0]
    assert amt(hc, "main_leg") == 3 * amt(one, "main_leg")
    assert sum(1 for o in q["options"] if o["recommended"]) == 1
    for o in q["options"]:
        assert D(o["total"]["max"]["amount"]) > D(o["total"]["min"]["amount"]) > 0


def test_huge_cargo_road_needs_multiple_trucks(client):
    o = post(client, req(origin=("TR", "Istanbul"), kg=60000, m3=200, modes=["road"]))["options"][0]
    assert "4 truck(s)" in line(o, "main_leg")["description"]  # ceil(200/60)=4 > ceil(60t/24t)=3
    small = post(client, req(origin=("TR", "Istanbul"), kg=12000, m3=40, modes=["road"]))["options"][0]
    assert amt(o, "main_leg") > 3 * amt(small, "main_leg")


def test_zero_or_negative_cargo_rejected(client):
    for kg in (0, -5):
        body = req()
        body["goods"]["total_weight_kg"] = str(kg)
        assert client.post("/v1/quotes/landed-cost", json=body).status_code == 422
    body = req()
    body["goods"]["total_volume_m3"] = "0"
    assert client.post("/v1/quotes/landed-cost", json=body).status_code == 422


# ------------------------------------------------------------------ ambiguous city names
def test_ambiguous_city_is_flagged_in_assumptions(client):
    q = post(client, req(dest=("US", "Springfield"), modes=["sea_fcl_40"]))
    note = next(a for a in q["assumptions"] if a.startswith("Ambiguous destination city"))
    assert "US-SPRINGFIELD_IL" in note and "US-SPRINGFIELD_MO" in note and "US-SPRINGFIELD_MA" in note
    assert "destination.point" in note


def test_explicit_point_or_unambiguous_city_has_no_ambiguity_note(client):
    body = req(dest=("US", "Springfield"), modes=["sea_fcl_40"])
    body["destination"]["point"] = {"lat": 37.21, "lon": -93.29}
    assert not any("Ambiguous" in a for a in post(client, body)["assumptions"])
    assert not any("Ambiguous" in a for a in post(client, req(dest=("US", "Houston")))["assumptions"])


@pytest.mark.asyncio
async def test_http_geo_city_candidates_exact_names_only_and_cached():
    import httpx

    from ff_logistics.clients.geo import CachedGeo, HttpGeo
    calls = []
    items = [{"id": f"US-SPRINGFIELD_{s}", "name_en": "Springfield", "country_code": "US",
              "point": {"lat": 40.0 + i, "lon": -90.0}} for i, s in enumerate(["IL", "MO"])]
    items.append({"id": "US-SPRINGFIELD_GARDENS", "name_en": "Springfield Gardens", "country_code": "US",
                  "point": {"lat": 40.6, "lon": -73.7}})

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"items": items, "total": len(items)})
    geo = CachedGeo(HttpGeo("http://geo", httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    found = await geo.city_candidates("US", "springfield")
    assert [m.id for m in found] == ["US-SPRINGFIELD_IL", "US-SPRINGFIELD_MO"]  # partial match excluded
    await geo.city_candidates("US", "springfield")
    assert calls == ["/v1/cities"]
