"""QA round: landed-cost invariants (exact Decimal arithmetic, deterministic mocks, no network)."""
import re
from decimal import Decimal as D

import pytest

from ff_logistics.domain import cargo
from ff_logistics.testing import req

ROUTES = [
    (("CN", "Shanghai"), ("IQ", "Baghdad"), 18000, 60),
    (("CN", "Yiwu"), ("IQ", "Erbil"), 2500, 6),
    (("CN", "Guangzhou"), ("AE", "Dubai"), 900, 4),
    (("DE", "Hamburg"), ("IQ", "Basra"), 9000, 25),
    (("CN", "Ningbo"), ("TR", "Istanbul"), 12000, 30),
    (("CN", "Shenzhen"), ("DE", "Hamburg"), 5000, 20),
]
CURRENCIES = ["USD", "EUR", "IQD", "CNY", "AED"]


def post(client, body):
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def amt(m):
    return D(m["amount"])


def lsum(o):
    return sum((amt(ln["amount"]) for ln in o["lines"]), D(0))


def main_leg(o):
    return next(ln for ln in o["lines"] if ln["stage"] == "main_leg")


@pytest.mark.parametrize("origin,dest,kg,m3", ROUTES)
@pytest.mark.parametrize("cur", CURRENCIES)
@pytest.mark.parametrize("inc", ["EXW", "FOB", "CIF", "DDP"])
def test_invariants_every_option(client, origin, dest, kg, m3, cur, inc):
    q = post(client, req(origin=origin, dest=dest, kg=kg, m3=m3, inc=inc, display_currency=cur))
    assert q["currency"] == cur and q["options"]
    assert sum(o["recommended"] for o in q["options"]) == 1
    for o in q["options"]:
        tmin, tmax = amt(o["total"]["min"]), amt(o["total"]["max"])
        mid = (tmin + tmax) / 2
        assert mid == lsum(o)  # exact: total mid is the sum of lines
        assert tmin <= mid <= tmax and tmin >= 0
        for ln in o["lines"]:
            assert ln["amount"]["currency"] == cur
            assert re.fullmatch(r"[A-Z]{3}", ln["original_amount"]["currency"])
            assert ln["source"].strip() and ln["as_of"].endswith("Z") and ln["description"]
            assert amt(ln["amount"]) >= 0  # duties/taxes/fees are never negative
            if ln["estimate"]:
                lo, hi = amt(ln["range"]["min"]), amt(ln["range"]["max"])
                assert 0 <= lo <= amt(ln["amount"]) <= hi  # low <= mid <= high
            else:
                assert "range" not in ln
        assert next(ln for ln in o["lines"] if ln["stage"] == "goods")["estimate"] is False


@pytest.mark.parametrize("origin,dest,kg,m3", ROUTES)
def test_deterministic_with_mocks(client, origin, dest, kg, m3):
    def norm(q):
        q = dict(q)
        for k in ("id", "created_at"):
            q.pop(k)
        s = repr(q)
        return re.sub(r"priced \d{4}-[0-9T:\-]+Z|\"as_of\": '[^']+'|'as_of': '[^']+'", "T", s)

    body = req(origin=origin, dest=dest, kg=kg, m3=m3)
    assert norm(post(client, body)) == norm(post(client, body))


def test_duties_and_taxes_never_negative_across_destinations(client):
    for dc, city in [("IQ", "Baghdad"), ("TR", "Istanbul"), ("AE", "Dubai"), ("DE", "Berlin"), ("SA", "Riyadh"),
                     ("US", "Chicago"), ("ZZ", None)]:
        for cat in ("machinery", "textiles", "electronics", None):
            body = req(dest=(dc, city), kg=2000, m3=8)
            body["goods"]["category"] = cat
            r = client.post("/v1/quotes/landed-cost", json=body)
            if r.status_code != 200:
                assert r.status_code in (400, 422)
                continue
            for o in r.json()["options"]:
                for ln in o["lines"]:
                    if ln["stage"] in ("duties", "taxes", "clearance"):
                        assert amt(ln["amount"]) >= 0 and amt(ln["range"]["min"]) >= 0


def air_line(client, kg, m3):
    q = post(client, req(origin=("CN", "Guangzhou"), kg=kg, m3=m3, value="1000", modes=["air"]))
    return main_leg(q["options"][0])


def chargeable(line):
    return D(re.search(r"Air (\d+) kg chargeable", line["description"]).group(1))


def test_air_chargeable_is_max_of_actual_and_volumetric():
    assert cargo.air_chargeable_kg(D(100), D(1)) == D(167)
    assert cargo.air_chargeable_kg(D(500), D(1)) == D(500)
    # 167 kg/m3 is the rounded 1 m3 / 6000 cm3 per kg (166.67): within 0.2 %
    assert abs(cargo.AIR_KG_PER_M3 - D(1_000_000) / 6000) / (D(1_000_000) / 6000) < D("0.002")


@pytest.mark.parametrize("kg,m3", [(100, 0.1), (100, 1), (100, 3), (800, 0.5), (800, 6), (50, 4)])
def test_air_description_uses_chargeable_weight(client, kg, m3):
    ln = air_line(client, kg, m3)
    assert chargeable(ln) == cargo.air_chargeable_kg(D(kg), D(str(m3))).quantize(D(1))


def test_air_volumetric_shipment_costs_same_as_equal_actual_weight(client):
    heavy_small = air_line(client, 1002, 0.1)  # chargeable 1002 actual
    light_big = air_line(client, 100, 6)  # chargeable 1002 volumetric
    assert chargeable(heavy_small) == chargeable(light_big) == D(1002)
    assert heavy_small["amount"] == light_big["amount"]


def test_air_cost_scales_with_chargeable_weight(client):
    costs = [amt(air_line(client, kg, 0.1)["amount"]) for kg in (50, 100, 200, 500, 1000, 2000)]
    assert costs == sorted(costs) and len(set(costs)) == len(costs)
    vols = [amt(air_line(client, 100, m3)["amount"]) for m3 in (0.2, 1, 2, 4, 6)]
    assert vols == sorted(vols)
    # more volume never makes a shipment cheaper once volumetric weight dominates
    assert amt(air_line(client, 100, 6)["amount"]) > amt(air_line(client, 100, 0.6)["amount"])


def test_sea_lcl_fcl_switchover_is_sane(client):
    modes = ["sea_lcl", "sea_fcl_20", "sea_fcl_40"]
    seen_fcl_rec = False
    prev_lcl = D(0)
    for m3 in (1, 3, 5, 10, 20, 25, 28, 30, 40, 58):
        q = post(client, req(kg=m3 * 200, m3=m3, value="20000", modes=modes))
        by = {o["mode"]: amt(main_leg(o)["amount"]) for o in q["options"]}
        if "sea_lcl" in by:
            assert by["sea_lcl"] >= prev_lcl  # LCL grows with volume
            prev_lcl = by["sea_lcl"]
        else:
            assert m3 > 30  # LCL is withdrawn only for big cargo
        rec = next(o["mode"] for o in q["options"] if o["recommended"])
        if m3 <= 3:
            assert rec == "sea_lcl"  # tiny cargo: LCL beats a whole container
        if m3 >= 30:
            assert rec != "sea_lcl"
        if rec.startswith("sea_fcl"):
            seen_fcl_rec = True
        else:
            assert not seen_fcl_rec  # once FCL wins it keeps winning as volume grows
        if m3 <= 28 and "sea_lcl" in by and by["sea_lcl"] < by["sea_fcl_20"]:
            assert m3 < 20  # LCL stays cheaper than a 20' only well below a full box
    assert seen_fcl_rec


def test_container_math():
    assert cargo.containers_needed(cargo.CONTAINERS["sea_fcl_40"], D(1000), D(58)) == 1
    assert cargo.containers_needed(cargo.CONTAINERS["sea_fcl_40"], D(1000), D("58.01")) == 2
    assert cargo.containers_needed(cargo.CONTAINERS["sea_fcl_20"], D(25001), D(1)) == 2
    assert cargo.lcl_revenue_tons(D(100), D("0.1")) == D(1)  # minimum 1 W/M


@pytest.mark.parametrize("cur", ["EUR", "IQD", "CNY", "AED", "JPY", "TRY"])
def test_fx_round_trip(client, cur):
    for start in ("1", "1234.56", "100000", "0.5"):
        r1 = client.post("/v1/fx/convert", json={"amount": start, "from": "USD", "to": cur}).json()
        r2 = client.post("/v1/fx/convert", json={"amount": r1["amount"]["amount"], "from": cur, "to": "USD"}).json()
        # error bound: half a minor unit of the foreign currency expressed in USD, plus USD rounding
        minor = D(1) if cur in ("IQD", "JPY") else D("0.01")
        tol = minor / 2 / D(r1["rate"]) + D("0.005")
        assert abs(D(r2["amount"]["amount"]) - D(start)) <= tol


def test_fx_cross_rates_consistent(client):
    def conv(a, f, t):
        return D(client.post("/v1/fx/convert", json={"amount": a, "from": f, "to": t}).json()["rate"])
    assert conv("1", "EUR", "CNY") * conv("1", "CNY", "EUR") == pytest.approx(D(1), rel=D("1e-9"))
    assert conv("1", "USD", "USD") == 1


def test_display_currency_does_not_change_value(client):
    base = post(client, req(display_currency="USD"))
    for cur, rate in (("EUR", D("0.92")), ("IQD", D("1310"))):
        q = post(client, req(display_currency=cur))
        for ob, oq in zip(base["options"], q["options"], strict=True):
            assert ob["mode"] == oq["mode"]
            tb = (amt(ob["total"]["min"]) + amt(ob["total"]["max"])) / 2
            tq = (amt(oq["total"]["min"]) + amt(oq["total"]["max"])) / 2
            # per-line rounding in the display currency only
            assert abs(tq / rate - tb) <= len(oq["lines"]) * (D("0.005") if cur != "IQD" else D("0.5") / rate) + D("0.01")
