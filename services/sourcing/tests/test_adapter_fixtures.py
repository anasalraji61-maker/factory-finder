"""Real-adapter parsers against hand-authored SYNTHETIC fixtures (tests/fixtures/*).

IMPORTANT: none of these fixtures is a recorded provider response and no real endpoint is verified.
They pin OUR parsing robustness (missing fields, null prices, HTML error pages, 429 + Retry-After,
pagination end, duplicates, currency/unit variants, https-only images, supplier identity).
No network: httpx.MockTransport with an injected clock.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from ff_sourcing.adapters._norm import (
    norm_name,
    read_price,
    safe_http_url,
    safe_image_urls,
    supplier_key,
    to_moq,
)
from ff_sourcing.adapters.alibaba_openapi import (
    ACCESS_TOKEN_ENV,
    APP_KEY_ENV,
    APP_SECRET_ENV,
)
from ff_sourcing.adapters.aliexpress import AliExpressAdapter
from ff_sourcing.adapters.http_base import (
    HostRateLimiter,
    SourceBlocked,
    parse_retry_after,
)
from ff_sourcing.adapters.licensed_rest import LicensedRestAdapter, load_mapping
from ff_sourcing.adapters.made_in_china import MadeInChinaAdapter
from ff_sourcing.adapters.source_1688 import Source1688Adapter
from ff_sourcing.config import Settings
from ff_sourcing.domain.models import SearchQuery

FIX = Path(__file__).parent / "fixtures"
BEARER = Path(__file__).parents[1] / "examples" / "licensed" / "example_fictional_bearer.mapping.json"
Q = SearchQuery(q="pp granules", keywords_en=["pp", "granules"], limit=50)
ENV = {APP_KEY_ENV: "k", APP_SECRET_ENV: "s3", ACCESS_TOKEN_ENV: "t"}


def load(name):
    return json.loads((FIX / name).read_text())


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.slept.append(d)
        self.t += d


def _settings():
    return Settings(
        aliexpress_app_key="k", aliexpress_app_secret="s", aliexpress_tracking_id="t",
        s1688_app_key="k", s1688_app_secret="s",
        mic_api_base="https://feed.example.invalid", mic_api_key="k",
    )


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _api(cls, handler, clock=None):
    clock = clock or Clock()
    lim = HostRateLimiter(3.0, clock=clock, sleep=clock.sleep)
    return cls(_settings(), client=_client(handler), limiter=lim), clock


def _json(payload):
    return lambda req: httpx.Response(200, json=payload)


def _alibaba(handler, clock=None):
    from ff_sourcing.adapters.alibaba_openapi import AlibabaOpenApiAdapter as A

    clock = clock or Clock()
    return A(client=_client(handler), env=ENV, clock=clock, sleep=clock.sleep), clock


ADAPTERS = {
    "aliexpress": (AliExpressAdapter, "aliexpress_affiliate_query.json"),
    "source_1688": (Source1688Adapter, "s1688_search.json"),
    "made_in_china": (MadeInChinaAdapter, "mic_feed_search.json"),
}


async def run(name):
    cls, fx = ADAPTERS[name]
    a, _ = _api(cls, _json(load(fx)))
    return await a.search(Q)


# ------------------------------------------------------------------ shared invariants
@pytest.mark.parametrize("name", list(ADAPTERS))
async def test_every_fixture_yields_only_sane_listings(name):
    items = await run(name)
    assert items, name
    ids = [i.id for i in items]
    assert len(ids) == len(set(ids)), "duplicate ids must be collapsed"
    for i in items:
        assert i.price.min.amount > 0 and i.price.max.amount >= i.price.min.amount
        assert len(i.price.min.currency) == 3 and i.price.min.currency.isupper()
        assert i.title and i.supplier.name and i.supplier.id.startswith(f"sup_{name}_")
        assert all(u.startswith("https://") for u in i.images)
        assert i.source_url is None or i.source_url.startswith(("http://", "https://"))


# ------------------------------------------------------------------ AliExpress
async def test_aliexpress_mapping_and_edge_cases():
    items = {i.id: i for i in await run("aliexpress")}
    fan = items["lst_aliexpress_1005001234567890"]
    assert (fan.price.min.amount, fan.price.max.amount) == (Decimal("3.20"), Decimal("4.99"))
    assert fan.price.min.currency == "USD" and fan.moq == 1 and fan.unit == "piece"
    assert fan.images == ["https://ae01.alicdn.com/kf/Sfake1.jpg", "https://ae01.alicdn.com/kf/Sfake2.jpg"]
    assert fan.source_url == "https://s.click.aliexpress.com/e/_fakeLink1"
    assert fan.supplier.id == "sup_aliexpress_1100200300"
    led = items["lst_aliexpress_1005009999999991"]
    assert led.price.min.amount == Decimal("1299.00") and led.price.min.currency == "CNY"
    assert led.source_url == "https://www.aliexpress.com/item/1005009999999991.html"  # javascript: link dropped
    assert led.images == []  # protocol-relative image refused
    assert "lst_aliexpress_1005000000000002" not in items  # null price
    assert "lst_aliexpress_1005000000000003" not in items  # zero price
    assert "lst_aliexpress_1005000000000004" not in items  # no title
    noshop = items["lst_aliexpress_1005000000000005"]
    assert noshop.supplier.name == "Unknown supplier" and noshop.supplier.id == "sup_aliexpress_unknown-1005000000000005"
    assert len(items) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"aliexpress_affiliate_product_query_response": None},
        {"aliexpress_affiliate_product_query_response": {"resp_result": {"result": {"products": None}}}},
        {"aliexpress_affiliate_product_query_response": {"resp_result": {"result": {"products": {"product": "x"}}}}},
    ],
)
async def test_aliexpress_odd_envelopes_are_empty_not_errors(payload):
    a, _ = _api(AliExpressAdapter, _json(payload))
    assert await a.search(Q) == []


# ------------------------------------------------------------------ 1688
async def test_1688_mapping_currency_units_supplier_identity():
    items = {i.id: i for i in await run("source_1688")}
    pp = items["lst_source_1688_612345678901"]
    assert (pp.price.min.amount, pp.price.max.amount) == (Decimal("12.5"), Decimal("15.00"))
    assert pp.price.min.currency == "CNY" and pp.moq == 100 and pp.unit == "kg" and pp.supplier.verified
    assert pp.supplier.name == "宁波 塑料 有限公司"  # NFKC + whitespace collapse (ideographic space)
    assert pp.supplier.id == "sup_source_1688_b2b-2200123456"
    assert pp.title == "PP 注塑级 颗粒"  # first duplicate wins
    line = items["lst_source_1688_612345678902"]
    assert line.price.max.amount == Decimal("28000.5") and line.unit == "set" and not line.supplier.verified
    assert line.supplier.id == "sup_source_1688_n-苏州-机械厂"  # no memberId: stable slug of the name
    assert line.images == ["https://cbu01.alicdn.com/img/ibank/ok2.jpg"]  # http and // refused
    usd = items["lst_source_1688_612345678905"]
    assert usd.price.min.currency == "USD" and usd.source_url is None  # ftp: dropped
    assert set(items) == {
        "lst_source_1688_612345678901", "lst_source_1688_612345678902", "lst_source_1688_612345678905"
    }


@pytest.mark.parametrize("payload", [{}, {"result": None}, {"result": {"toReturn": None}}, {"result": {"toReturn": {}}}])
async def test_1688_odd_envelopes(payload):
    a, _ = _api(Source1688Adapter, _json(payload))
    assert await a.search(Q) == []


def test_1688_symbol_without_country_hint_not_guessed_as_yen():
    # parse as domestic wholesale: bare yen sign means CNY for this adapter
    item = Source1688Adapter(Settings()).normalize_item(
        {"offerId": 1, "subject": "t", "price": "¥3", "memberId": "m", "companyName": "c"}
    )
    assert item.price.min.currency == "CNY"


# ------------------------------------------------------------------ Made-in-China feed
async def test_mic_mapping_and_variants():
    items = {i.id: i for i in await run("made_in_china")}
    cnc = items["lst_made_in_china_mic-1001"]
    assert (cnc.price.min.amount, cnc.price.max.amount) == (Decimal("18500"), Decimal("21000"))
    assert cnc.price.min.currency == "USD" and cnc.moq == 1 and cnc.unit == "set" and cnc.supplier.verified
    assert cnc.images == ["https://image.made-in-china.com/fake/a.jpg"]
    valve = items["lst_made_in_china_mic-1002"]
    assert (valve.price.min.amount, valve.price.max.amount) == (Decimal("3.50"), Decimal("4.20"))
    assert valve.unit == "pc" and valve.moq == 500 and not valve.supplier.verified
    assert valve.images == ["https://image.made-in-china.com/fake/v.jpg"]  # deduped
    assert items["lst_made_in_china_mic-1003"].price.min.currency == "CNY"  # RMB alias
    euro = items["lst_made_in_china_mic-1005"]
    assert euro.price.min.amount == Decimal("12.50") and euro.price.min.currency == "EUR"
    flip = items["lst_made_in_china_mic-1006"]
    assert (flip.price.min.amount, flip.price.max.amount) == (Decimal(4), Decimal(9))
    assert not {"lst_made_in_china_mic-1004", "lst_made_in_china_mic-1007"} & set(items)  # null / garbage price
    assert len(items) == 5


@pytest.mark.parametrize("payload", [{}, {"items": None}, {"items": "oops"}, {"items": [1, None, "x"]}])
async def test_mic_odd_envelopes(payload):
    a, _ = _api(MadeInChinaAdapter, _json(payload))
    assert await a.search(Q) == []


# ------------------------------------------------------------------ Alibaba OpenAPI (generic provider)
async def test_alibaba_openapi_edge_fixture():
    a, _ = _alibaba(lambda r: httpx.Response(200, json=load("alibaba_openapi_edge.json")))
    items = {i.id: i for i in await a.search(Q)}
    lad = items["lst_alibaba_openapi_1"]
    assert (lad.price.min.amount, lad.price.max.amount) == (Decimal("5.00"), Decimal("8.00"))
    assert lad.moq == 1000 and lad.supplier.verified and lad.supplier.name == "Foshan Ceramics Co"
    assert lad.supplier.id == "sup_alibaba_openapi_cn1"
    assert lad.images == ["https://s.alicdn.com/1.jpg"]
    assert items["lst_alibaba_openapi_2"].price.min.currency == "CNY"  # 'RMB 80/pc' read via pricing parser
    assert items["lst_alibaba_openapi_5"].supplier.name == "Unknown supplier"
    assert items["lst_alibaba_openapi_6"].source_url is None and items["lst_alibaba_openapi_6"].origin.country_code == "CN"
    assert not {"lst_alibaba_openapi_3", "lst_alibaba_openapi_4"} & set(items)
    assert len(items) == 4


async def test_alibaba_openapi_original_fixture_still_parses_and_skips_idless():
    a, _ = _alibaba(lambda r: httpx.Response(200, json=load("alibaba_openapi_search.json")))
    assert [i.id for i in await a.search(Q)] == ["lst_alibaba_openapi_1600123456", "lst_alibaba_openapi_1600123457"]


# ------------------------------------------------------------------ HTML error page / non-JSON / wrong shape
HTML = (FIX / "html_error_page.html").read_text()


@pytest.mark.parametrize("status", [200, 202])
@pytest.mark.parametrize("name", list(ADAPTERS))
async def test_html_page_is_a_block_not_a_crash(name, status):
    cls, _ = ADAPTERS[name]
    a, _ = _api(cls, lambda r: httpx.Response(status, text=HTML, headers={"content-type": "text/html"}))
    with pytest.raises(SourceBlocked):
        await a.search(Q)


async def test_html_page_provider_adapter_and_licensed_rest():
    a, _ = _alibaba(lambda r: httpx.Response(200, text=HTML))
    with pytest.raises(SourceBlocked):
        await a.search(Q)
    spec = load_mapping(BEARER)
    clock = Clock()
    lr = LicensedRestAdapter(spec, client=_client(lambda r: httpx.Response(200, text=HTML)),
                             env={"FF_SOURCING_EXAMPLIA_API_KEY": "k" * 12}, clock=clock, sleep=clock.sleep)
    with pytest.raises(SourceBlocked):
        await lr.search(Q)


@pytest.mark.parametrize("body", ["[]", "[1,2]", "null", '"str"'])
async def test_non_object_json_is_rejected(body):
    a, _ = _alibaba(lambda r: httpx.Response(200, text=body))
    with pytest.raises(SourceBlocked):
        await a.search(Q)
    b, _ = _api(AliExpressAdapter, lambda r: httpx.Response(200, text=body))
    with pytest.raises(SourceBlocked):
        await b.search(Q)


async def test_http_5xx_error_redacts_signed_url():
    a, _ = _alibaba(lambda r: httpx.Response(500))
    with pytest.raises(RuntimeError) as e:
        await a.search(Q)
    assert "sign=" not in str(e.value) and "app_key" not in str(e.value) and "s3" not in str(e.value)


# ------------------------------------------------------------------ 429 + Retry-After
@pytest.mark.parametrize("which", ["api", "provider"])
async def test_429_retry_after_is_honoured_without_retrying(which):
    calls, clock = [], Clock()

    def h(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(200, json=load("alibaba_openapi_search.json") if which == "provider" else {"items": []})

    if which == "provider":
        a, _ = _alibaba(h, clock)
        q2 = SearchQuery(q="other", keywords_en=["other"])
    else:
        a, _ = _api(MadeInChinaAdapter, h, clock)
        q2 = SearchQuery(q="other", keywords_en=["other"])
    with pytest.raises(SourceBlocked) as e:
        await a.search(Q)
    assert e.value.retry_after_s == 120 and len(calls) == 1
    clock.t += 60  # still cooling: no request is made, remaining time is reported
    with pytest.raises(SourceBlocked) as e2:
        await a.search(q2)
    assert len(calls) == 1 and 59 <= e2.value.retry_after_s <= 61
    clock.t += 61  # cooldown over: calls resume
    await a.search(q2)
    assert len(calls) == 2


async def test_429_without_or_with_garbage_header_uses_default_and_cap():
    for hdr, expect in ((None, 60), ({"Retry-After": "soon"}, 60), ({"Retry-After": "999999"}, 3600)):
        a, _ = _api(MadeInChinaAdapter, lambda r, hdr=hdr: httpx.Response(429, headers=hdr or {}))
        with pytest.raises(SourceBlocked) as e:
            await a.search(Q)
        assert e.value.retry_after_s == expect


def test_retry_after_parser_formats():
    assert parse_retry_after("7") == 7 and parse_retry_after(None) is None and parse_retry_after("x") is None
    when = datetime.now(UTC) + timedelta(seconds=90)
    got = parse_retry_after(format_datetime(when, usegmt=True))
    assert 85 <= got <= 91
    past = format_datetime(datetime.now(UTC) - timedelta(hours=1), usegmt=True)
    assert parse_retry_after(past) == 0


async def test_401_403_still_blocked_without_cooldown_state():
    for code in (401, 403):
        a, _ = _api(MadeInChinaAdapter, lambda r, c=code: httpx.Response(c))
        with pytest.raises(SourceBlocked) as e:
            await a.search(Q)
        assert e.value.retry_after_s is None


# ------------------------------------------------------------------ licensed REST: pagination end, duplicates
def _spec(pages=3):
    s = json.loads(BEARER.read_text())
    s["pagination"]["max_pages"] = pages
    return s


def _lr(handler, spec):
    clock = Clock()
    return LicensedRestAdapter(
        load_mapping(spec), client=_client(handler), env={"FF_SOURCING_EXAMPLIA_API_KEY": "k" * 12},
        clock=clock, sleep=clock.sleep,
    ), clock


async def test_licensed_pagination_stops_at_empty_page_and_dedupes_across_pages():
    seen = []
    pages = {"1": load("licensed_pages_p1.json"), "2": load("licensed_pages_p2.json")}

    def h(req):
        seen.append(req.url.params["page"])
        return httpx.Response(200, json=pages.get(req.url.params["page"], {"data": {"items": []}}))

    a, clock = _lr(h, _spec(5))
    items = {i.id: i for i in await a.search(Q)}
    assert seen == ["1", "2", "3"]  # page 3 empty => stop, pages 4-5 never requested
    assert set(items) == {"lst_examplia_trade_p-1", "lst_examplia_trade_p-3"}  # null price dropped, p-1 not repeated
    p1 = items["lst_examplia_trade_p-1"]
    assert p1.images == ["https://img.examplia.invalid/1.jpg"]  # http:// and non-allowlisted host refused
    assert p1.price.min.currency == "USD" and p1.unit == "piece" and p1.moq == 1
    p3 = items["lst_examplia_trade_p-3"]
    assert p3.price.min.amount == Decimal("9800") and p3.price.min.currency == "CNY"  # 'RMB 9,800' via parser
    assert all(s >= 3.0 - 1e-9 for s in clock.slept)


async def test_licensed_stops_when_limit_reached():
    seen = []

    def h(req):
        seen.append(req.url.params["page"])
        return httpx.Response(200, json=load("licensed_pages_p1.json"))

    a, _ = _lr(h, _spec(5))
    await a.search(SearchQuery(q="x", keywords_en=["x"], limit=2))
    assert seen == ["1"]


async def test_licensed_429_on_second_page_keeps_first_and_cools_down():
    n = []

    def h(req):
        n.append(1)
        if req.url.params["page"] == "2":
            return httpx.Response(429, headers={"Retry-After": "30"})
        return httpx.Response(200, json=load("licensed_pages_p1.json"))

    a, clock = _lr(h, _spec(3))
    assert len(await a.search(Q)) == 1  # partial results kept
    assert len(n) == 2  # page 3 never requested after the 429
    with pytest.raises(SourceBlocked):
        await a.search(SearchQuery(q="y", keywords_en=["y"]))  # still cooling: no new request
    assert len(n) == 2


# ------------------------------------------------------------------ helpers
@pytest.mark.parametrize(
    "value,expected",
    [
        ("US $12.50-15.00", (Decimal("12.50"), Decimal("15.00"), "USD")),
        ("12,50 €", (Decimal("12.50"), Decimal("12.50"), "EUR")),
        (3.5, (Decimal("3.5"), Decimal("3.5"), None)),
        ("1,234.50", (Decimal("1234.50"), Decimal("1234.50"), None)),
        ("RMB 80/件", (Decimal(80), Decimal(80), "CNY")),
    ],
)
def test_read_price_variants(value, expected):
    p = read_price(value)
    assert (p.lo, p.hi, p.currency) == expected


@pytest.mark.parametrize("value", [None, "", "N/A", "面议", "0", 0, -5, True, "Negotiable", float("nan"), "abc"])
def test_read_price_rejects_unusable(value):
    assert read_price(value) is None


def test_image_and_url_validation():
    assert safe_image_urls(["https://a.example/x.jpg", "http://a.example/y.jpg", "//a.example/z.jpg",
                            "data:image/png;base64,xx", "javascript:alert(1)", "https://u:p@a.example/q.jpg",
                            "https://a.example/x.jpg", "https:///nohost", "https://a.example/sp ace.jpg", None, 5]) == [
        "https://a.example/x.jpg"
    ]
    assert safe_image_urls("https://a.example/1.jpg") == ["https://a.example/1.jpg"]
    assert safe_image_urls({"a": 1}) == [] and len(safe_image_urls([f"https://a.example/{i}" for i in range(30)])) == 8
    assert safe_http_url("http://a.example/x") and not safe_http_url("ftp://a.example") and not safe_http_url("//a.example")


def test_supplier_identity_normalization():
    from ff_sourcing.adapters._norm import norm_country

    assert norm_country("cn") == "CN" and norm_country("China") == "CN" and norm_country("Narnia") == "CN" and norm_country(None, "US") == "US"
    assert norm_name("  Foshan　 Ceramics\tCo​ ") == "Foshan Ceramics Co"
    assert norm_name(None) == "" and norm_name({"a": 1}) == ""
    assert supplier_key(" cn1 ", "x") == "cn1" and supplier_key(None, "Wuxi  Lathes") == "n-wuxi-lathes"
    assert supplier_key("None", "A B") == "n-a-b" and supplier_key("", "", "L9") == "unknown-L9"
    assert to_moq("20 Tons") == 20 and to_moq("1,000") == 1000 and to_moq(0) is None and to_moq("n/a") is None
    assert to_moq(True) is None
