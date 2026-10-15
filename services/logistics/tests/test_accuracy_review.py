"""Accuracy review 2026-10: realistic lanes vs rough market benchmarks (mock geo/FX, no network)."""
from decimal import Decimal

import pytest

from ff_logistics.domain import cargo
from ff_logistics.domain.duties import load_json
from ff_logistics.schemas import LandedCostRequest
from ff_logistics.testing import req

D = Decimal


async def quote(engine, **kw):
    return await engine.quote(LandedCostRequest.model_validate(req(**kw)))


def line(opt, stage):
    return next((ln for ln in opt["lines"] if ln["stage"] == stage), None)


def amt(opt, stage):
    ln = line(opt, stage)
    return D(ln["amount"]["amount"]) if ln else D(0)


async def test_sea_fcl_china_iraq_benchmarks(engine):
    q20 = await quote(engine, origin=("CN", "Shenzhen"), dest=("IQ", "Basra"), kg=18000, m3=25,
                      value="40000", modes=["sea_fcl_20"])
    q40 = await quote(engine, origin=("CN", "Shenzhen"), dest=("IQ", "Basra"), kg=22000, m3=58,
                      value="80000", modes=["sea_fcl_40"])
    o20, o40 = q20["options"][0], q40["options"][0]
    assert D(1000) <= amt(o20, "main_leg") <= D(3500)
    assert D(1800) <= amt(o40, "main_leg") <= D(5000)
    assert amt(o20, "main_leg") < amt(o40, "main_leg") < amt(o20, "main_leg") * 2  # 40' cheaper per TEU
    assert amt(o40, "duties") == (D("80000") + amt(o40, "origin_inland") + amt(o40, "origin_handling")
                                  + amt(o40, "main_leg") + amt(o40, "insurance")) * D("0.05")
    assert amt(o40, "taxes") == 0  # Iraq has no VAT
    assert D("0.002") <= amt(o40, "insurance") / D("80000") <= D("0.006")


async def test_air_500kg_rate_per_kg(engine):
    q = await quote(engine, origin=("CN", "Guangzhou"), dest=("IQ", "Erbil"), kg=500, m3=2,
                    value="15000", modes=["air"])
    per_kg = amt(q["options"][0], "main_leg") / 500
    assert D(2.5) <= per_kg <= D(8)


async def test_europe_and_us_lanes(engine):
    qh = await quote(engine, origin=("CN", "Shanghai"), dest=("DE", "Hamburg"), kg=20000, m3=58,
                     value="60000", modes=["sea_fcl_40"])
    oh = qh["options"][0]
    assert D(1500) <= amt(oh, "main_leg") <= D(5000)
    assert abs(amt(oh, "taxes") - (D("60000") + sum(amt(oh, s) for s in
            ("origin_inland", "origin_handling", "main_leg", "insurance")) + amt(oh, "duties")) * D("0.19")) < D("0.1")
    ql = await quote(engine, origin=("CN", "Ningbo"), dest=("US", "Los Angeles"), kg=20000, m3=58,
                     value="60000", modes=["sea_fcl_40"])
    ol = ql["options"][0]
    assert D(2500) <= amt(ol, "main_leg") <= D(7000)
    assert "additional duty" in line(ol, "duties")["description"]


async def test_full_truck_is_not_discounted_but_half_empty_is(engine):
    assert cargo.truck_billing_factor(D(20000), D(50)) == 1  # 83% full -> billed as a full truck
    assert cargo.truck_billing_factor(D(100000), D(500)) == 1  # several trucks
    assert cargo.truck_billing_factor(D(1000), D(1)) == D("0.3")
    half = cargo.truck_billing_factor(D(12000), D(30))
    assert D("0.3") < half < 1
    q = await quote(engine, origin=("TR", "Istanbul"), dest=("IQ", "Baghdad"), kg=20000, m3=50,
                    value="30000", modes=["road"])
    ml = line(q["options"][0], "main_leg")
    assert "LTL" not in ml["description"]
    assert D(2500) <= D(ml["amount"]["amount"]) <= D(6500)  # ~2,100 km, FTL benchmark ~USD 3-4.5k


async def test_incoterm_stage_handling(engine):
    kw = dict(origin=("CN", "Shanghai"), dest=("IQ", "Basra"), kg=20000, m3=58, value="50000",
              modes=["sea_fcl_40"])
    cif = (await quote(engine, inc="CIF", **kw))["options"][0]
    assert line(cif, "main_leg") is None and line(cif, "insurance") is None
    assert amt(cif, "duties") == D("2500.00")  # customs value = supplier CIF price only
    ddp = (await quote(engine, inc="DDP", **kw))["options"][0]
    assert [ln["stage"] for ln in ddp["lines"]] == ["goods"]
    assert ddp["total"]["min"] == ddp["total"]["max"]
    fob = (await quote(engine, inc="FOB", **kw))["options"][0]
    assert line(fob, "origin_inland") is None and line(fob, "origin_handling") is None
    assert amt(fob, "duties") == (D(50000) + amt(fob, "main_leg") + amt(fob, "insurance")) * D("0.05")


async def test_every_line_has_currency_source_timestamp_and_range(engine):
    q = await quote(engine, origin=("CN", "Shanghai"), dest=("DE", "Hamburg"), kg=20000, m3=58,
                    value="60000", display_currency="EUR")
    assert q["options"]
    for o in q["options"]:
        total = D(0)
        for ln in o["lines"]:
            assert ln["amount"]["currency"] == "EUR" and ln["original_amount"]["currency"]
            assert ln["source"] and ln["source"].count("priced 20") == 1 and "FX " in ln["source"]
            assert isinstance(ln["estimate"], bool)
            if ln["stage"] != "goods":
                assert ln["estimate"] is True
            total += D(ln["amount"]["amount"])
        lo, hi = D(o["total"]["min"]["amount"]), D(o["total"]["max"]["amount"])
        assert lo < total < hi  # estimates carry a range around the sum of the lines
        assert o["total"]["min"]["currency"] == "EUR"


async def test_zero_decimal_currency_sums_exactly(engine):
    q = await quote(engine, origin=("CN", "Shanghai"), dest=("IQ", "Basra"), kg=20000, m3=58,
                    value="50000", display_currency="IQD", modes=["sea_fcl_40"])
    o = q["options"][0]
    assert all("." not in ln["amount"]["amount"] for ln in o["lines"])
    total = sum(D(ln["amount"]["amount"]) for ln in o["lines"])
    assert D(o["total"]["min"]["amount"]) < total < D(o["total"]["max"]["amount"])
    assert D(line(o, "goods")["amount"]["amount"]) == D(50000) * D(1310)


async def test_missing_data_fallbacks_are_disclosed(engine):
    body = req(dest=("KP", None), modes=["sea_fcl_40"])
    body["destination"]["point"] = {"lat": 39.0, "lon": 125.7}
    body["destination"].pop("city")
    q = await engine.quote(LandedCostRequest.model_validate(body))
    text = " ".join(q["assumptions"])
    assert "No duty/VAT table for destination KP" in text
    assert "not in the region table" in text


def test_duty_table_sanity_ranges():
    t = load_json("duties.json")["countries"]
    for cc, c in t.items():
        assert 0 <= D(str(c["default_duty_pct"])) <= 60, cc
        assert 0 <= D(str(c["vat_pct"])) <= 27.5, cc
        assert 0 <= D(str(c["clearance_fee_usd"])) <= 500, cc
        assert all(0 <= D(str(v)) <= 100 for v in c["chapters"].values()), cc
    assert t["RU"]["vat_pct"] == 22  # raised from 20% on 2026-01-01
    assert t["SA"]["vat_pct"] == 15 and t["AE"]["vat_pct"] == 5 and t["IQ"]["vat_pct"] == 0


@pytest.mark.parametrize("m3,kg", [(0.01, 1), (0.1, 50), (30, 20000)])
async def test_tiny_and_large_cargo_never_zero_or_crash(engine, m3, kg):
    q = await quote(engine, origin=("CN", "Shenzhen"), dest=("AE", "Dubai"), kg=kg, m3=m3, value="100")
    for o in q["options"]:
        assert D(o["total"]["min"]["amount"]) > 0
        assert amt(o, "main_leg") > 0
