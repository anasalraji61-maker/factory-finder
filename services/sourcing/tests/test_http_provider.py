"""HttpProviderAdapter / AlibabaOpenApiAdapter against recorded fixtures (httpx.MockTransport)."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ff_sourcing.adapters.alibaba_openapi import (
    ACCESS_TOKEN_ENV,
    APP_KEY_ENV,
    APP_SECRET_ENV,
    AlibabaOpenApiAdapter,
)
from ff_sourcing.adapters.http_base import SourceBlocked, SourceNotConfigured
from ff_sourcing.adapters.http_provider import (
    GLOBAL_KILL_SWITCH_ENV,
    HttpProviderAdapter,
    ProviderConfig,
    ProviderDisabled,
    get_path,
    parse_price_range,
)
from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry, build_registry
from ff_sourcing.clients.trust import MockTrustClient
from ff_sourcing.config import Settings
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.service import SourcingService

FIX = json.loads((Path(__file__).parent / "fixtures" / "alibaba_openapi_search.json").read_text())
SECRET = "top-secret-value"
ENV = {APP_KEY_ENV: "k1", APP_SECRET_ENV: SECRET, ACCESS_TOKEN_ENV: "tok"}
Q = SearchQuery(q="pp granules", keywords_en=["pp", "granules"])


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.slept.append(d)
        self.t += d


def make(handler, env=None, clock=None):
    clock = clock or Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = AlibabaOpenApiAdapter(client=client, env=ENV if env is None else env, clock=clock, sleep=clock.sleep)
    return a, clock


def ok_handler(calls):
    def h(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json=FIX)

    return h


async def test_mapping_to_listing_contract():
    calls = []
    a, _ = make(ok_handler(calls))
    items = await a.search(Q)
    assert [i.id for i in items] == ["lst_alibaba_openapi_1600123456", "lst_alibaba_openapi_1600123457"]
    first = items[0]
    assert first.price.min.amount == Decimal("900.00") and first.price.max.amount == Decimal("1100.50")
    assert isinstance(first.price.max.amount, Decimal) and first.price.min.currency == "USD"
    assert first.moq == 20 and first.unit == "ton" and first.images == [
        "https://s.alicdn.com/a.jpg",
        "https://s.alicdn.com/b.jpg",
    ]
    assert first.supplier.id == "sup_alibaba_openapi_cn123" and first.supplier.verified
    assert first.origin.country_code == "CN" and first.origin.city == "Ningbo"
    second = items[1]  # single price -> degenerate range, default currency, unverified
    assert second.price.min.amount == second.price.max.amount == Decimal("25000")
    assert second.price.min.currency == "USD" and not second.supplier.verified


async def test_request_is_signed_honest_and_secret_not_leaked():
    calls = []
    a, _ = make(ok_handler(calls))
    await a.search(Q)
    req = calls[0]
    assert req.headers["user-agent"].startswith("FactoryFinderBot/")
    assert "sign" in req.url.params and req.url.params["keywords"] == "pp granules"
    assert SECRET not in str(req.url) and SECRET not in str(req.headers)
    assert SECRET not in repr(a) and a.config.min_interval_s >= 3.0


async def test_unconfigured_and_defaults_off():
    a, _ = make(ok_handler([]), env={})
    assert not a.configured()
    with pytest.raises(SourceNotConfigured):
        await a.search(Q)
    reg = build_registry(Settings())
    assert [x.id for x in reg.enabled()] == ["mock"] and "alibaba_openapi" in {x.id for x in reg.all()}
    assert reg.fallback().id == "mock"
    on = build_registry(Settings(adapters="alibaba_openapi"))
    assert {x.id for x in on.enabled()} == {"mock", "alibaba_openapi"}


async def test_rate_limit_and_cache_with_injected_clock():
    calls = []
    a, clock = make(ok_handler(calls))
    await a.search(Q)
    await a.search(Q)  # cached: no request, no sleep (timestamp/sign excluded from key)
    assert len(calls) == 1 and clock.slept == []
    await a.search(SearchQuery(q="other", keywords_en=["other"]))
    assert len(calls) == 2 and clock.slept == [3.0]  # >= 3s between calls to the same host
    clock.t += 301  # TTL (300s) expires -> refetch
    await a.search(Q)
    assert len(calls) == 3


async def test_cache_ttl_boundary():
    calls = []
    a, clock = make(ok_handler(calls))
    await a.search(Q)
    clock.t += 299
    await a.search(Q)
    assert len(calls) == 1


@pytest.mark.parametrize("env_name", [GLOBAL_KILL_SWITCH_ENV, "FF_SOURCING_ALIBABA_OPENAPI_DISABLED"])
async def test_kill_switch(env_name):
    calls = []
    a, _ = make(ok_handler(calls), env={**ENV, env_name: "1"})
    with pytest.raises(ProviderDisabled):
        await a.search(Q)
    assert calls == [] and (await a.health()).ok is False


@pytest.mark.parametrize("code", [401, 403, 429])
async def test_blocked_statuses_not_retried(code):
    calls = []

    def h(request):
        calls.append(1)
        return httpx.Response(code)

    a, _ = make(h)
    with pytest.raises(SourceBlocked):
        await a.search(Q)
    assert len(calls) == 1


def test_helpers_and_generic_config_mapping():
    assert get_path({"a": [{"b": 1}, {"b": 2}]}, "a[].b") == [1, 2]
    assert get_path({"a": [{"b": 1}]}, "a[0].b") == 1 and get_path({}, "x.y") is None
    assert parse_price_range("US $12.50 - 15") == (Decimal("12.50"), Decimal("15"))
    assert parse_price_range("15-12") == (Decimal("12"), Decimal("15")) and parse_price_range("n/a") is None
    cfg = ProviderConfig(
        id="feed", name="Feed", base_url="https://feed.example/api", min_interval_s=0.1,
        api_key_env="FEED_KEY", results_path="data", currency_default="CNY",
        field_map={"id": "i", "title": "t", "price_min": "p.lo", "price_max": "p.hi"},
    )
    a = HttpProviderAdapter(cfg, env={"FEED_KEY": "zzz"})
    assert a.limiter.min_interval_s == 3.0  # floor enforced
    assert a.build_headers()["Authorization"] == "Bearer zzz"
    li = a.normalize_item({"i": 5, "t": "x", "p": {"lo": "7.5", "hi": "7.9"}})
    assert li.price.max.amount == Decimal("7.9") and li.price.min.currency == "CNY"
    assert a.normalize_item({"t": "no id"}) is None


# ---- service-level degradation -------------------------------------------------
def service_with(handler, env=None):
    a, _ = make(handler, env=env)
    reg = AdapterRegistry([MockAdapter(), a], enabled={"alibaba_openapi"})
    return SourcingService(reg, MockTrustClient(), cache_ttl_s=0.0), reg


async def test_service_falls_back_to_mock_on_5xx():
    svc, _ = service_with(lambda r: httpx.Response(503))
    res = await svc.search(SearchQuery(q="plastic"))
    st = res.sources[0]
    assert st.source == "alibaba_openapi" and st.status == "error" and "mock results" in st.warning
    assert res.total > 0 and all(i.source == "mock" for i in res.items)


async def test_service_falls_back_on_timeout_and_killswitch_and_unconfigured():
    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    for handler, env in [(boom, None), (ok_handler([]), {**ENV, GLOBAL_KILL_SWITCH_ENV: "true"}), (ok_handler([]), {})]:
        svc, _ = service_with(handler, env)
        res = await svc.search(SearchQuery(q="plastic"))
        assert res.sources[0].status == "error" and res.sources[0].warning and res.total > 0


async def test_service_uses_real_results_when_healthy():
    svc, _ = service_with(ok_handler([]))
    res = await svc.search(SearchQuery(q="pp granules"))
    assert res.sources[0].status == "ok" and res.sources[0].warning is None
    assert res.items and res.items[0].source == "alibaba_openapi"


async def test_no_double_mock_when_mock_already_enabled():
    a, _ = make(lambda r: httpx.Response(500))
    reg = AdapterRegistry([MockAdapter(), a], enabled={"mock", "alibaba_openapi"})
    res = await SourcingService(reg, MockTrustClient()).search(SearchQuery(q="plastic"))
    bad = [s for s in res.sources if s.source == "alibaba_openapi"][0]
    assert bad.count == 0 and bad.status == "error"
