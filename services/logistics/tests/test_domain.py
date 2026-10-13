from decimal import Decimal as D

import pytest

from ff_logistics.adapters.fx import EcbFx, FxService, MockFx
from ff_logistics.domain import cargo
from ff_logistics.domain.duties import duty_rule, hs_chapter
from ff_logistics.domain.engine import DATA, air_rate_per_kg
from ff_logistics.domain.incoterms import BUYER_STAGES
from ff_logistics.domain.warnings import sanctions_warning


def test_air_chargeable_weight():
    assert cargo.air_chargeable_kg(D(100), D(1)) == D(167)  # volumetric wins
    assert cargo.air_chargeable_kg(D(500), D(1)) == D(500)  # actual wins


def test_lcl_wm():
    assert cargo.lcl_revenue_tons(D(200), D("0.3")) == D(1)  # minimum 1
    assert cargo.lcl_revenue_tons(D(3500), D(2)) == D("3.5")  # weight wins
    assert cargo.lcl_revenue_tons(D(900), D(4)) == D(4)  # volume wins


def test_container_fitting():
    c20, c40, hc = (cargo.CONTAINERS[k] for k in ("sea_fcl_20", "sea_fcl_40", "sea_fcl_40hc"))
    assert cargo.containers_needed(c20, D(10000), D(20)) == 1
    assert cargo.containers_needed(c20, D(10000), D(29)) == 2  # volume
    assert cargo.containers_needed(c20, D(26000), D(10)) == 2  # weight
    assert cargo.containers_needed(c40, D(1000), D(60)) == 2
    assert cargo.containers_needed(hc, D(1000), D(60)) == 1
    assert cargo.fill_ratio(hc, D(1000), D(34)) == D("0.5")


def test_incoterm_stage_sets():
    assert "origin_inland" in BUYER_STAGES["EXW"] and "origin_inland" not in BUYER_STAGES["FCA"]
    assert "origin_handling" in BUYER_STAGES["FCA"] and "main_leg" not in BUYER_STAGES["CFR"]
    assert "insurance" in BUYER_STAGES["CFR"] and "insurance" not in BUYER_STAGES["CIF"]
    assert BUYER_STAGES["DAP"] == {"duties", "taxes", "clearance"} and not BUYER_STAGES["DDP"]


def test_air_weight_breaks():
    lane = DATA.lanes["lanes"]["EAS>GULF"]
    assert air_rate_per_kg(lane, D(20)) > air_rate_per_kg(lane, D(120)) > air_rate_per_kg(lane, D(2000))


@pytest.mark.parametrize("hs,cat,expected", [("8501.10", None, "85"), (None, "furniture", "94"), (None, None, None)])
def test_hs_chapter(hs, cat, expected):
    assert hs_chapter(hs, cat, DATA.duties) == expected


def test_duties_by_chapter_and_country():
    t = DATA.duties
    assert duty_rule(t, "IQ", "6109", None).duty_rate_pct == D(20)  # apparel
    assert duty_rule(t, "IQ", "8501", None).duty_rate_pct == D(5)
    assert duty_rule(t, "IR", "8703", None).duty_rate_pct == D(100)
    assert duty_rule(t, "DE", "7208", None).vat_pct == D(19)
    us = duty_rule(t, "US", "8501", None, "CN")  # +15% additional on CN origin
    assert us.duty_rate_pct == D("16.5") and "additional" in us.rule
    assert duty_rule(t, "ZZ", None, None).rule.startswith("ZZ")


def test_all_15_destinations_have_tables():
    assert {"IQ", "TR", "IR", "JO", "SA", "AE", "KW", "EG", "US", "DE", "FR", "GB", "IT", "IN", "RU"} <= set(
        DATA.duties["countries"])


def test_sanctions_warning():
    assert "IR" in sanctions_warning({"CN", "IR"})
    assert sanctions_warning({"CN", "IQ"}) is None


async def test_fx_mock_and_cross_rates():
    fx = FxService(MockFx())
    rate, _ = await fx.rate("USD", "IQD")
    assert rate == D(1310)
    eur_gbp, _ = await fx.rate("EUR", "GBP")
    assert eur_gbp == D("0.79") / D("0.92")
    with pytest.raises(Exception):
        await fx.rate("USD", "XXX")


async def test_ecb_fallback_and_cache(respx_mock):
    url = "https://example.test/latest"
    route = respx_mock.get(url).respond(json={"date": "2026-10-12", "rates": {"EUR": 0.9, "TRY": 40}})
    ecb = EcbFx(url, ttl=1000)
    r1 = await ecb.usd_rates()
    assert r1.source == "ecb" and r1.rates["EUR"] == D("0.9") and r1.rates["IQD"] == D(1310)  # gap filled
    await ecb.usd_rates()
    assert route.call_count == 1  # cached
    respx_mock.get(url).respond(500)
    r2 = await EcbFx(url).usd_rates()
    assert r2.source == "mock-fallback"


NEW_DESTINATIONS = ["SY", "LB", "LY", "DZ", "MA", "TN", "PK", "BD", "NG", "KE", "ZA", "BR", "PL", "ES", "NL",
                    "CA", "AU", "QA", "OM", "BH", "VN", "ID", "MY", "TH", "KR", "JP"]


def test_extended_duty_tables_valid():
    countries = DATA.duties["countries"]
    assert len(countries) >= 30 and set(NEW_DESTINATIONS) <= set(countries)
    for cc, c in countries.items():
        assert 0 <= c["default_duty_pct"] <= 100 and 0 <= c["vat_pct"] <= 30, cc
        assert c["clearance_fee_usd"] > 0, cc
        assert set(c["chapters"]) >= {"39", "84", "85", "87"}, cc
        assert all(0 <= v <= 100 for v in c["chapters"].values()), cc
    assert "approximate" in DATA.duties["note"]
    assert duty_rule(DATA.duties, "BR", "8501", None).vat_pct == D(17)


def test_every_known_region_has_handling_and_lanes():
    regions = set(DATA.lanes["regions"].values())
    assert {"AFR", "LAM", "OCE"} <= regions
    for r in regions:
        assert r in DATA.handling["origin"] and r in DATA.handling["destination"], r
    for key, lane in DATA.lanes["lanes"].items():
        a, b = key.split(">")
        assert a in regions and b in regions, key
        assert lane["fcl_20"] < lane["fcl_40"] <= lane["fcl_40hc"]
        assert lane["sea_days"][0] < lane["sea_days"][1]
        assert [x[0] for x in lane["air_breaks"]] == sorted(x[0] for x in lane["air_breaks"])
    assert set(DATA.lanes["continents"]) == set(DATA.lanes["regions"])
