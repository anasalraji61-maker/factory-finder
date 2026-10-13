import httpx
import pytest
import respx

from ff_sourcing.adapters.alibaba import AlibabaAdapter
from ff_sourcing.adapters.aliexpress import AliExpressAdapter
from ff_sourcing.adapters.http_base import (
    HostRateLimiter,
    HttpRequestSpec,
    SourceBlocked,
    SourceNotConfigured,
    hmac_sign,
)
from ff_sourcing.adapters.made_in_china import MadeInChinaAdapter
from ff_sourcing.adapters.source_1688 import Source1688Adapter
from ff_sourcing.config import Settings
from ff_sourcing.domain.models import SearchQuery

ALL = (AlibabaAdapter, AliExpressAdapter, MadeInChinaAdapter, Source1688Adapter)
SECRET = "s3cr3t-value"


def test_disabled_and_unconfigured_by_default():
    from ff_sourcing.adapters.registry import build_registry

    reg = build_registry(Settings())
    assert [a.id for a in reg.enabled()] == ["mock"]
    for cls in ALL:
        a = cls(Settings())
        assert not a.configured() and SECRET not in repr(a) and a.compliance


async def test_unconfigured_search_raises_without_network():
    with pytest.raises(SourceNotConfigured):
        await AlibabaAdapter(Settings()).search(SearchQuery(q="x"))


def test_request_building_is_signed_and_secret_not_sent():
    s = Settings(
        alibaba_app_key="k",
        alibaba_app_secret=SECRET,
        aliexpress_app_key="k",
        aliexpress_app_secret=SECRET,
        aliexpress_tracking_id="t",
        s1688_app_key="k",
        s1688_app_secret=SECRET,
    )
    q = SearchQuery(q="خط انتاج", keywords_en=["production line"])
    for cls in (AlibabaAdapter, AliExpressAdapter, Source1688Adapter):
        spec = cls(s).build_search_request(q)
        flat = str(spec.params) + str(spec.headers) + spec.url
        assert SECRET not in flat
        assert any(k in spec.params for k in ("sign", "_aop_signature"))
    assert AlibabaAdapter(s).build_search_request(q).params["keyword"] == "production line"
    assert hmac_sign({"b": 2, "a": 1}, "x") == hmac_sign({"a": 1, "b": 2}, "x")


def test_normalization_skeletons():
    s = Settings()
    a = AlibabaAdapter(s).normalize_item(
        {
            "id": 7,
            "subject": "PP granules",
            "price": {"min": "900", "max": "1,100"},
            "seller_id": 3,
            "seller_name": "ACME",
            "moq": "20",
            "verified_supplier": True,
        }
    )
    assert a.id == "lst_alibaba_7" and str(a.price.max.amount) == "1100" and a.supplier.verified
    b = Source1688Adapter(s).normalize_item({"offerId": 1, "subject": "t", "price": "12.5"})
    assert b.price.min.currency == "CNY" and b.price.max.amount == b.price.min.amount
    c = AliExpressAdapter(s).normalize_item({"product_id": 9, "target_sale_price": "3.2"})
    assert c.moq == 1
    d = MadeInChinaAdapter(s).normalize_item(
        {"id": 5, "title": "x", "price_min": 5, "price_max": 4}
    )
    assert d.price.min.amount < d.price.max.amount  # swapped to a valid range


async def test_rate_limiter_enforces_interval():
    now = [0.0]
    slept = []

    async def sleep(d):
        slept.append(d)
        now[0] += d

    lim = HostRateLimiter(3.0, clock=lambda: now[0], sleep=sleep)
    await lim.wait("h1")
    await lim.wait("h1")
    await lim.wait("h2")
    assert slept == [3.0]


@respx.mock
async def test_fetch_caches_and_blocks_on_403():
    s = Settings(alibaba_app_key="k", alibaba_app_secret=SECRET)
    route = respx.get("https://openapi-api.alibaba.com/products/search").mock(
        return_value=httpx.Response(200, json={"result": {"products": []}})
    )
    async with httpx.AsyncClient() as c:
        a = AlibabaAdapter(s, client=c, limiter=HostRateLimiter(0))
        await a.search(SearchQuery(q="x"))
        await a.search(SearchQuery(q="x"))
        assert route.call_count == 1  # cached
        route.mock(return_value=httpx.Response(403))
        with pytest.raises(SourceBlocked):
            await a.fetch(
                HttpRequestSpec(
                    url="https://openapi-api.alibaba.com/products/search", params={"p": 2}
                )
            )


@respx.mock
async def test_robots_txt_enforced_for_public_pages():
    s = Settings(mic_api_base="https://www.made-in-china.com/api", mic_allow_public_pages=True)
    respx.get("https://www.made-in-china.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /api")
    )
    page = respx.get("https://www.made-in-china.com/api/search").mock(
        return_value=httpx.Response(200, json={})
    )
    async with httpx.AsyncClient() as c:
        a = MadeInChinaAdapter(s, client=c, limiter=HostRateLimiter(0))
        with pytest.raises(SourceBlocked):
            await a.search(SearchQuery(q="x"))
    assert page.call_count == 0
