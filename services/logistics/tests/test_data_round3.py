"""Data round 3: duty/VAT coverage, de minimis, sensitivity (freight/FX), exactness and monotonicity."""
from decimal import Decimal as D

import pytest

from ff_logistics.domain import engine as eng
from ff_logistics.domain.duties import de_minimis, duty_rule
from ff_logistics.domain.engine import DATA, haul_cost, inland_days, synth_lane
from ff_logistics.domain.money import ZERO_DECIMAL
from ff_logistics.domain.sensitivity import currency_vol_pct, pair_vol_pct, sensitivity
from ff_logistics.testing import req

NEW = ["KZ", "UZ", "AZ", "GE", "UA", "GR", "BE", "RO", "CZ", "AT", "SE", "PT", "HU", "BG", "CH", "RS", "MX", "AR",
       "CL", "CO", "PE", "GH", "SN", "CN", "HK", "SG", "TW", "PH", "LK"]
CONF = {"high", "medium", "low"}


def rq(dest, value="40000", cur="USD", **kw):
    kw.setdefault("modes", None)
    body = req(dest=dest, value=value, **kw)
    body["goods"]["total_value"]["currency"] = cur
    return body


def post(client, body):
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_new_countries_have_labelled_sourced_ranged_entries():
    countries = DATA.duties["countries"]
    assert len(NEW) >= 25 and len(countries) >= 70 and set(NEW) <= set(countries)
    assert DATA.duties["label"] == "indicative, verify with broker"
    for cc in NEW:
        c = countries[cc]
        assert c["label"] == "indicative, verify with broker" and c["source"] and c["as_of"] == "2026-10", cc
        assert c["confidence"] in CONF, cc
        lo, hi = c["duty_range_pct"]
        assert 0 <= lo <= hi <= 100, cc
        assert lo <= c["default_duty_pct"] <= hi and all(lo <= v <= hi for v in c["chapters"].values()), cc
        vlo, vhi = c["vat_range_pct"]
        assert vlo <= c["vat_pct"] <= vhi, cc
        assert set(c["chapters"]) >= {"39", "52", "61", "62", "72", "73", "84", "85", "87", "94"}, cc
        assert DATA.region(cc) in DATA.handling["destination"], cc


def test_every_country_with_a_table_has_a_region():
    for cc in DATA.duties["countries"]:
        assert cc in DATA.lanes["regions"] and cc in DATA.lanes["continents"], cc


def test_de_minimis_records_valid():
    found = 0
    for cc, c in DATA.duties["countries"].items():
        dm = c.get("de_minimis")
        if dm is None:
            continue
        found += 1
        assert dm["threshold"] > 0 and len(dm["currency"]) == 3 and dm["scope"], cc
        assert dm["status"] in {"in_force", "suspended", "being_phased_out", "uncertain"}, cc
        assert dm["confidence"] in CONF and dm["applies_to"], cc
        assert de_minimis(DATA.duties, cc) == dm
    assert found >= 25
    assert de_minimis(DATA.duties, "IQ") is None and de_minimis(DATA.duties, "ZZ") is None


def test_origin_surcharge_and_ranges_carry_through_duty_rule():
    r = duty_rule(DATA.duties, "MX", "8501", None, "CN")
    assert r.duty_rate_pct == D(5) + D(15) and r.duty_range_pct == (D(0) + 15, D(35) + 15)
    assert r.as_of == "2026-10" and r.confidence == "low"
    assert duty_rule(DATA.duties, "IQ", "8501", None).duty_range_pct is None  # legacy entries unchanged


@pytest.mark.parametrize(("dc", "city"), [("GH", "Accra"), ("PE", "Lima"), ("MX", "Mexico City"), ("LK", "Colombo"),
                                           ("SE", "Stockholm"), ("GR", "Athens"), ("CH", "Zurich"), ("KZ", "Almaty")])
def test_quote_to_new_destinations(client, dc, city):
    modes = ["air"] if dc in {"CH", "KZ"} else ["sea_fcl_40hc", "air"]
    q = post(client, rq((dc, city), modes=modes, kg=500, m3=2))
    for o in q["options"]:
        duty = next(ln for ln in o["lines"] if ln["stage"] == "duties")
        assert "indicative" in duty["source"] and "as of 2026-10" in duty["source"] and "range" in duty["description"]
        tmin, tmax = D(o["total"]["min"]["amount"]), D(o["total"]["max"]["amount"])
        assert tmin <= (tmin + tmax) / 2 <= tmax


def test_duty_range_widens_the_total_range_even_at_zero_duty(client):
    body = rq(("CH", "Zurich"), modes=["air"], kg=500, m3=2)
    body["goods"]["hs_code"] = "8501"
    q = post(client, body)
    o = q["options"][0]
    duty = next(ln for ln in o["lines"] if ln["stage"] == "duties")
    assert D(duty["amount"]["amount"]) == 0
    lo, hi = D(o["total"]["min"]["amount"]), D(o["total"]["max"]["amount"])
    base = sum(D(ln["amount"]["amount"]) for ln in o["lines"])
    non_duty_spread = sum(D(ln["amount"]["amount"]) * D(eng.SPREAD[ln["stage"]]) for ln in o["lines"]
                          if ln["stage"] != "duties" and ln["estimate"])
    assert (hi - lo) / 2 > non_duty_spread - D(1) and lo < base < hi


def test_de_minimis_warning_only_below_threshold_and_never_changes_totals(client):
    small = post(client, rq(("DE", "Berlin"), value="100", modes=["air"], kg=500, m3=2))
    assert any("de minimis" in w and "do NOT assume any waiver" in w for w in small["warnings"])
    big = post(client, rq(("DE", "Berlin"), value="50000", modes=["air"], kg=500, m3=2))
    assert not any("de minimis" in w for w in big["warnings"])
    duty = next(ln for ln in small["options"][0]["lines"] if ln["stage"] == "duties")
    assert D(duty["amount"]["amount"]) > 0  # no waiver applied


def test_de_minimis_unknown_fx_currency_does_not_break_quote(client, monkeypatch):
    monkeypatch.setitem(DATA.duties["countries"]["DE"], "de_minimis",
                        {"threshold": 5, "currency": "XYZ", "applies_to": "duty", "status": "uncertain",
                         "confidence": "low", "scope": "x"})
    q = post(client, rq(("DE", "Berlin"), modes=["air"], kg=500, m3=2))
    assert q["options"]


# ------------------------------------------------------------------ sensitivity
def money_exact(m, cur):
    assert m["currency"] == cur
    places = 0 if cur in ZERO_DECIMAL else 2
    amt = D(m["amount"])
    assert amt == amt.quantize(D(1).scaleb(-places)) and (("." in m["amount"]) == bool(places))
    return amt


@pytest.mark.parametrize("disp", ["USD", "IQD", "EUR", "JPY", "TRY"])
def test_sensitivity_exact_labelled_and_consistent(client, disp):
    q = post(client, rq(("IQ", "Baghdad"), "12345.67", "CNY", display_currency=disp))
    for o in q["options"]:
        s = o["sensitivity"]
        assert s["currency"] == disp and s["estimate"] is True and "not a forecast" in s["note"]
        base = sum(money_exact(ln["amount"], disp) for ln in o["lines"])
        for key in ("freight", "fx", "combined"):
            low, b, high = (money_exact(s[key][k], disp) for k in ("low", "base", "high"))
            assert low <= b == base <= high, (disp, key)
        main = next(ln for ln in o["lines"] if ln["stage"] == "main_leg")
        f = s["freight"]
        assert money_exact(f["high"], disp) - base == (D(main["amount"]["amount"]) * D(eng.SPREAD["main_leg"]))\
            .quantize(D(1) if disp in ZERO_DECIMAL else D("0.01"), rounding="ROUND_HALF_UP")
        assert D(f["shock_pct"]) == D("15")
        fx_d = money_exact(s["fx"]["high"], disp) - base
        fr_d = money_exact(f["high"], disp) - base
        assert money_exact(s["combined"]["high"], disp) - base == fx_d + fr_d
        assert money_exact(s["combined"]["low"], disp) == max(base - fx_d - fr_d, D(0))
        # freight sensitivity sits inside the published estimate range
        assert money_exact(o["total"]["max"], disp) >= money_exact(f["high"], disp) - D(1)


def test_sensitivity_fx_zero_only_when_nothing_is_exposed(client):
    q = post(client, rq(("IQ", "Baghdad"), "20000", display_currency="USD"))
    for o in q["options"]:
        assert D(o["sensitivity"]["fx"]["shock_pct"]) == 0
        assert o["sensitivity"]["fx"]["low"] == o["sensitivity"]["fx"]["high"]
    q = post(client, rq(("IQ", "Baghdad"), "20000", "TRY", display_currency="USD"))
    assert all(D(o["sensitivity"]["fx"]["shock_pct"]) > 0 for o in q["options"])


def test_sensitivity_unit_math_is_decimal_exact():
    s = sensitivity(D("1000.00"), D("200.00"), D("0.15"), D("500.00"), "EUR", "USD")
    assert s["freight"]["high"] == {"amount": "1030.00", "currency": "USD"}
    assert s["freight"]["low"]["amount"] == "970.00"
    assert s["fx"]["high"]["amount"] == "1020.00"  # 500 goods x 4% EUR vs USD; others in USD, 0%
    assert s["combined"]["high"]["amount"] == "1050.00" and "shock_pct" not in s["combined"]
    z = sensitivity(D("1000"), D(0), D("0.15"), D(0), "USD", "JPY")
    assert z["fx"]["high"]["amount"] == "1050" and z["freight"]["high"]["amount"] == "1000"
    assert sensitivity(D(0), D(0), D("0.15"), D(0), "USD", "USD")["fx"]["shock_pct"] == "0"


def test_fx_volatility_table():
    assert currency_vol_pct("USD") == 0 and currency_vol_pct("AED") < currency_vol_pct("EUR") < currency_vol_pct("TRY")
    assert currency_vol_pct("ZZZ") == D(8)  # documented default
    assert pair_vol_pct("EUR", "EUR") == 0 and pair_vol_pct("EUR", "TRY") == pair_vol_pct("TRY", "EUR") == D(12)


# ------------------------------------------------------------------ monotonicity / exactness
def test_synthetic_lane_transit_and_cost_monotonic_in_distance():
    prev = None
    for km in range(100, 30001, 250):
        lane = synth_lane(D(km))
        cur = (lane["sea_days"][0], lane["sea_days"][1], lane["fcl_40"], lane["lcl_per_wm"], lane["air_breaks"][1][1])
        assert lane["sea_days"][0] < lane["sea_days"][1] and lane["fcl_20"] < lane["fcl_40"] <= lane["fcl_40hc"]
        if prev:
            assert all(a >= b for a, b in zip(cur, prev, strict=True)), km
        prev = cur


def test_inland_days_and_haul_cost_monotonic():
    last_d, last_c = (0, 0), D(0)
    for km in range(0, 5001, 25):
        days = inland_days(D(km))
        cost = haul_cost("TR", D(km), D(8000), D(20))
        assert days[0] <= days[1] and days >= last_d and cost >= last_c, km
        last_d, last_c = days, cost


def test_money_lines_use_declared_currencies_everywhere(client):
    q = post(client, rq(("IQ", "Baghdad"), "9999.99", "CNY", display_currency="EUR"))
    assert q["currency"] == "EUR"
    for o in q["options"]:
        for ln in o["lines"]:
            assert ln["amount"]["currency"] == "EUR"
            orig = ln["original_amount"]["currency"]
            assert orig == ("CNY" if ln["stage"] == "goods" else "USD")
            D(ln["amount"]["amount"])  # exact decimal strings, no float artefacts
            D(ln["fx_rate"])
            assert "e" not in ln["amount"]["amount"].lower()
        for k in ("min", "max"):
            assert o["total"][k]["currency"] == "EUR"


def test_quote_longer_distance_never_has_shorter_transit_for_same_destination(client):
    from ff_logistics.clients.geo import CITIES, Point, haversine_km
    dest = CITIES[("IQ", "baghdad")]
    cities = sorted(("shanghai", "yiwu", "guangzhou", "urumqi"),
                    key=lambda c: haversine_km(Point(*CITIES[("CN", c)]), Point(*dest)))
    days = [post(client, req(origin=("CN", c), modes=["road"]))["options"][0]["transit_days"]["max"] for c in cities]
    assert days == sorted(days), (cities, days)
