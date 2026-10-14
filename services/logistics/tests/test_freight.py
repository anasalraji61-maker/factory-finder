"""Freight providers against a recorded fixture served by httpx.MockTransport (no network)."""
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ff_logistics.adapters.freight import (
    FreightQuote,
    FreightRequest,
    FreightUnavailable,
    HttpFreightProvider,
    MockFreight,
)
from ff_logistics.adapters.fx import FxService, MockFx
from ff_logistics.clients.geo import MockGeo
from ff_logistics.config import Settings
from ff_logistics.domain.engine import Engine
from ff_logistics.main import create_app
from ff_logistics.schemas import LandedCostRequest
from ff_logistics.testing import req

FIX = json.loads((Path(__file__).parent / "fixtures" / "freight_estimate.json").read_text())
FR = FreightRequest("sea_fcl_40", "CNSHA", "Shanghai", "CN", "IQUQR", "Umm Qasr", "IQ",
                    Decimal("18000"), Decimal("60"), 1)


class Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.slept.append(d)
        self.t += d


def provider(handler, key="k", env=None, clock=None, **kw):
    clock = clock or Clock()
    p = HttpFreightProvider("https://rates.example/api", key, env=env or {}, clock=clock,
                            sleep=clock.sleep, now_iso=lambda: "2026-10-14T00:00:00Z",
                            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)
    return p, clock


def ok(calls):
    def h(r):
        calls.append(r)
        return httpx.Response(200, json=FIX)
    return h


async def test_parse_quote_range_and_flags():
    calls = []
    p, _ = provider(ok(calls))
    q = await p.quote(FR)
    assert (q.low, q.high, q.currency) == (Decimal("2100"), Decimal("3900"), "USD")
    assert q.estimate is True and q.days == (28, 45) and "UNVERIFIED" in q.source
    r = calls[0]
    assert r.headers["user-agent"].startswith("FactoryFinderBot/") and r.url.params["loadtype"] == "container40"
    assert "sekret" not in repr(provider(ok([]), key="sekret")[0])
    assert "sekret" not in str(provider(ok([]), key="sekret")[0].__dict__.get("base_url"))


async def test_unsupported_mode_returns_none_and_mock_is_none():
    p, _ = provider(ok([]))
    assert await p.quote(FreightRequest("rail", "a", "a", "CN", "b", "b", "IQ", Decimal(1), Decimal(1))) is None
    assert await MockFreight().quote(FR) is None


async def test_cache_and_rate_limit_with_injected_clock():
    calls = []
    p, clock = provider(ok(calls), cache_ttl_s=100)
    await p.quote(FR)
    await p.quote(FR)
    assert len(calls) == 1 and clock.slept == []
    other = FreightRequest(**{**FR.__dict__, "dest_id": "IQBGW"})
    await p.quote(other)
    assert len(calls) == 2 and clock.slept == [3.0]
    clock.t += 101
    await p.quote(FR)
    assert len(calls) == 3


async def test_min_interval_floor():
    p, _ = provider(ok([]), min_interval_s=0.1)
    assert p.min_interval_s == 3.0


async def test_kill_switch_and_unconfigured():
    calls = []
    for env, key in [({"FF_LOGISTICS_FREIGHT_DISABLED": "1"}, "k"), ({"FF_LOGISTICS_KILL_SWITCH": "true"}, "k"), ({}, "")]:
        p, _ = provider(ok(calls), key=key, env=env)
        with pytest.raises(FreightUnavailable):
            await p.quote(FR)
    assert calls == []


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(503),
    lambda r: httpx.Response(429),
    lambda r: httpx.Response(200, text="not json"),
    lambda r: httpx.Response(200, json={"response": {}}),
])
async def test_errors_raise_unavailable_then_cool_down(handler):
    calls = []

    def h(r):
        calls.append(1)
        return handler(r)

    p, clock = provider(h, cooldown_s=60)
    with pytest.raises(FreightUnavailable):
        await p.quote(FR)
    other = FreightRequest(**{**FR.__dict__, "dest_id": "X"})
    with pytest.raises(FreightUnavailable, match="cooling"):
        await p.quote(other)
    assert len(calls) == 1  # no hammering a failing provider
    clock.t += 61
    with pytest.raises(FreightUnavailable):
        await p.quote(other)
    assert len(calls) == 2


async def test_timeout_is_unavailable():
    def h(r):
        raise httpx.ReadTimeout("slow", request=r)
    p, _ = provider(h)
    with pytest.raises(FreightUnavailable):
        await p.quote(FR)


# ---- engine integration ---------------------------------------------------------
def engine_with(freight, **kw):
    return Engine(MockGeo(), FxService(MockFx()), freight, **kw)


def sea_req():
    return LandedCostRequest.model_validate(req(modes=["sea_fcl_40"]))


def main_leg(opt):
    return next(ln for ln in opt["lines"] if ln["stage"] == "main_leg")


async def test_engine_default_matches_tables():
    base = await engine_with(None).quote(sea_req())
    mocked = await engine_with(MockFreight()).quote(sea_req())
    assert [o["total"] for o in base["options"]] == [o["total"] for o in mocked["options"]]
    assert "table" in main_leg(base["options"][0])["source"]


async def test_engine_uses_live_quote_with_honest_range():
    p, _ = provider(ok([]))
    q = await engine_with(p).quote(sea_req())
    ml = main_leg(q["options"][0])
    assert "UNVERIFIED" in ml["source"] and "2026-10-14" in ml["source"] and ml["estimate"] is True
    assert Decimal(ml["amount"]["amount"]) == Decimal("3000.00")  # midpoint of 2100..3900
    tot = q["options"][0]["total"]
    assert Decimal(tot["min"]["amount"]) < Decimal(tot["max"]["amount"])
    assert any("live rate" in a for a in q["assumptions"])
    # range reflects the quote's +-30% on the main leg (wider than the table's 15%)
    base = await engine_with(None).quote(sea_req())
    assert main_leg(base["options"][0])["source"] != ml["source"]


async def test_engine_falls_back_to_tables_on_5xx_with_note():
    p, _ = provider(lambda r: httpx.Response(500))
    q = await engine_with(p).quote(sea_req())
    base = await engine_with(None).quote(sea_req())
    assert [o["total"] for o in q["options"]] == [o["total"] for o in base["options"]]
    assert any("unavailable" in a and "built-in" in a for a in q["assumptions"])


async def test_engine_dangerous_goods_and_call_budget():
    calls = []
    p, _ = provider(ok(calls))
    body = req(modes=["sea_fcl_40"])
    body["goods"]["dangerous_goods"] = True
    await engine_with(p).quote(LandedCostRequest.model_validate(body))
    assert calls == []  # DG surcharges are table-only: never mix with an undifferentiated quote
    calls.clear()
    p, _ = provider(ok(calls))
    await engine_with(p, freight_max_calls=1).quote(sea_req())
    assert len(calls) <= 1


class CurrencyFreight:
    async def quote(self, r):
        return FreightQuote(Decimal("1000"), Decimal("1000"), "EUR", "x", "2026-10-14T00:00:00Z")


async def test_engine_converts_quote_currency_and_floors_spread():
    q = await engine_with(CurrencyFreight()).quote(sea_req())
    ml = main_leg(q["options"][0])
    assert Decimal(ml["amount"]["amount"]) > Decimal("1000")  # EUR -> USD at mock 0.92
    assert ml["original_amount"]["currency"] == "USD"


def test_api_app_wiring_defaults_to_mock_and_http_is_opt_in():
    c = TestClient(create_app(Settings(geo_provider="mock")))
    assert isinstance(c.app.state.freight, MockFreight)
    on = create_app(Settings(geo_provider="mock", freight_provider="http", freight_url="https://x.example"))
    assert isinstance(on.state.freight, HttpFreightProvider)
    off = create_app(Settings(geo_provider="mock", freight_provider="http"))  # no URL => stays mock
    assert isinstance(off.state.freight, MockFreight)
