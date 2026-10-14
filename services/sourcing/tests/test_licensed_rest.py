"""Licensed REST adapter, mapping validator and quality normalization. Fixtures only, no network."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ff_sourcing import licensed_validate
from ff_sourcing.adapters.http_base import SourceBlocked
from ff_sourcing.adapters.http_provider import ProviderDisabled
from ff_sourcing.adapters.licensed_rest import (
    LicensedRestAdapter,
    host_allowed,
    load_licensed_adapters,
    load_mapping,
)
from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry, build_registry
from ff_sourcing.clients.trust import MockTrustClient
from ff_sourcing.config import Settings
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.domain.quality import (
    dedupe_listings,
    detect_currency,
    price_is_sane,
    title_similarity,
)
from ff_sourcing.service import SourcingService

ROOT = Path(__file__).parents[1]
EX = ROOT / "examples" / "licensed"
FIX = Path(__file__).parent / "fixtures"
BEARER = EX / "example_fictional_bearer.mapping.json"
QKEY = EX / "example_fictional_query_key.mapping.json"
R1 = json.loads((FIX / "licensed_examplia_response.json").read_text())
R2 = json.loads((FIX / "licensed_sinoparts_response.json").read_text())
KEY = "sekrit-key-123456"
Q = SearchQuery(q="pp granules", keywords_en=["pp", "granules"], limit=50)


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.slept.append(d)
        self.t += d


def adapter(path, handler, env=None, spec_edit=None):
    spec = load_mapping(path)
    if spec_edit:
        spec = spec.model_copy(update=spec_edit)
    clock = Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = LicensedRestAdapter(
        spec, client=client, env={"FF_SOURCING_EXAMPLIA_API_KEY": KEY, "FF_SOURCING_SINOPARTS_KEY": KEY}
        if env is None else env, clock=clock, sleep=clock.sleep,
    )
    return a, clock


def ok(payload, calls=None):
    def h(req):
        if calls is not None:
            calls.append(req)
        return httpx.Response(200, json=payload)

    return h


# ---------------- mapping / validator ----------------
def test_examples_validate_and_are_labelled():
    for p in (BEARER, QKEY):
        spec = load_mapping(p)
        assert spec.example is True and "EXAMPLE" in spec.name
        assert ".invalid" in spec.base_url
        assert licensed_validate.main([str(p)]) == 0


def test_validator_sample_dry_run(capsys):
    assert licensed_validate.main([str(BEARER), "--sample", str(FIX / "licensed_examplia_response.json")]) == 0
    assert "SAMPLE 3/7 items normalized" in capsys.readouterr().out


def test_validator_flags_bad_mappings(tmp_path, capsys):
    base = json.loads(BEARER.read_text())

    def bad(**edits):
        d = json.loads(json.dumps(base))
        for k, v in edits.items():
            d[k] = v
        f = tmp_path / "m.json"
        f.write_text(json.dumps(d))
        return licensed_validate.main([str(f)])

    assert bad(base_url="http://insecure.example") == 1
    assert bad(auth={"style": "bearer", "key_env": "abc-real-key-value"}) == 1
    assert bad(tos_note="") == 1
    assert bad(fields={"id": "x"}) == 1
    assert bad(unknown_key=1) == 1
    assert bad(request={"path": "/s", "query": {"q": "{nope}"}}) == 1
    assert bad(request={"path": "/s", "query": {"x": "apikey=abcdefgh12345"}}) == 1
    assert bad(request={"path": "/s", "headers": {"Authorization": "x"}}) == 1
    assert bad(id="mock") == 1
    assert bad(units={"price_scale": "0"}) == 1
    assert bad(pagination={"style": "cursor"}) == 1
    assert bad(request={"method": "POST", "path": "/s"}) == 1
    assert "INVALID" in capsys.readouterr().out
    assert licensed_validate.main([str(tmp_path / "missing.json")]) == 1


def test_validator_warns_on_low_interval(tmp_path, capsys):
    d = json.loads(BEARER.read_text())
    d["limits"]["min_interval_s"] = 0.5
    d["pagination"]["max_pages"] = 3
    d["images"]["allowed_hosts"] = []
    f = tmp_path / "m.json"
    f.write_text(json.dumps(d))
    assert licensed_validate.main([str(f)]) == 0
    out = capsys.readouterr().out
    assert "clamped" in out and "ADAPTER_TIMEOUT" in out and "no image URLs" in out


# ---------------- adapter ----------------
async def test_bearer_auth_mapping_and_normalization():
    calls = []
    a, _ = adapter(BEARER, ok(R1, calls))
    items = await a.search(Q)
    req = calls[0]
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert "FactoryFinderBot" in req.headers["user-agent"]
    assert req.url.params["q"] == "pp granules" and req.url.params["page"] == "1"
    assert req.url.params["per_page"] == "40"
    assert "ship_from" not in req.url.params  # empty placeholder dropped
    # A1+A2 deduped (same supplier, near-identical title); A3 zero price, A4 absurd range, A5 JPY not allowed, no-id dropped
    ids = {i.id for i in items}
    assert len(items) == 2 and "lst_examplia_trade_A3" not in ids and "lst_examplia_trade_A5" not in ids
    a2 = next(i for i in items if i.id.endswith("A2"))  # richer duplicate (2 images) wins
    assert not any(i.id.endswith("A1") for i in items)
    assert a2.price.min.currency == "USD" and isinstance(a2.price.min.amount, Decimal)
    rmb = next(i for i in items if i.id.endswith("A6"))
    assert rmb.price.min.currency == "CNY"  # alias RMB -> CNY


async def test_image_allowlist_unit_alias_and_fields():
    r = json.loads(json.dumps(R1))
    r["data"]["items"][1]["seller"] = {"id": "S9", "name": "Different Seller"}
    a, _ = adapter(BEARER, ok(r))
    items = await a.search(Q)
    a1 = next(i for i in items if i.id.endswith("A1"))
    assert a1.images == ["https://img.examplia.invalid/a1.jpg"]  # foreign host + http dropped
    assert a1.unit == "ton" and a1.moq == 500 and a1.supplier.verified is True
    assert a1.description == "Virgin PP" and a1.category == "raw_materials"
    assert a1.origin.country_code == "CN" and a1.supplier.location.city == "Ningbo"


def test_host_allowed_rules():
    assert host_allowed("https://img.a.invalid/x", ["img.a.invalid"], True)
    assert host_allowed("https://x.cdn.a.invalid/x", [".cdn.a.invalid"], True)
    assert not host_allowed("https://cdn.a.invalid.evil.com/x", [".cdn.a.invalid"], True)
    assert not host_allowed("http://img.a.invalid/x", ["img.a.invalid"], True)
    assert not host_allowed("javascript:alert(1)", ["img.a.invalid"], False)
    assert not host_allowed("https://img.a.invalid/x", [], True)


async def test_query_key_offset_pagination_and_price_text():
    calls = []
    a, _ = adapter(QKEY, ok(R2, calls))
    items = await a.search(Q)
    p = calls[0].url.params
    assert p["apikey"] == KEY and p["keyword"] == "pp granules" and p["rows"] == "30" and p["start"] == "0"
    assert "authorization" not in calls[0].headers
    by = {i.id: i for i in items}
    k1, k2 = by["lst_sinoparts_feed_K-1"], by["lst_sinoparts_feed_K-2"]
    assert (k1.price.min.amount, k1.price.max.amount, k1.price.min.currency) == (Decimal("120.50"), Decimal("135"), "USD")
    assert k2.price.min.currency == "CNY" and k1.unit == "piece" and k1.moq == 2
    assert "lst_sinoparts_feed_K-3" not in by
    # query key is excluded from the cache key: second call served from cache
    await a.search(Q)
    assert len(calls) == 1


async def test_price_scale_minor_units():
    payload = {"data": {"items": [{"product_id": "m1", "name": "Thing", "pricing": {"min": 1250, "max": 1500, "currency": "USD"}, "seller": {"id": "s", "name": "Sup"}}]}}
    spec = json.loads(BEARER.read_text())
    spec["units"]["price_scale"] = "0.01"
    a, _ = adapter(spec, ok(payload))
    (it,) = await a.search(Q)
    assert it.price.min.amount == Decimal("12.50") and it.price.max.amount == Decimal("15.00")


def paged_handler(calls):
    pages = {
        "1": {"data": {"items": [{"product_id": "p1", "name": "Alpha Widget", "pricing": {"min": 1, "max": 2, "currency": "USD"}, "seller": {"id": "a", "name": "A"}}]}},
        "2": {"data": {"items": [{"product_id": "p2", "name": "Beta Gadget", "pricing": {"min": 1, "max": 2, "currency": "USD"}, "seller": {"id": "b", "name": "B"}}]}},
    }

    def h(req):
        calls.append(req.url.params["page"])
        pg = req.url.params["page"]
        return httpx.Response(200, json=pages.get(pg, {"data": {"items": []}}))

    return h


async def test_page_pagination_throttle_and_partial_failure():
    calls = []
    spec = json.loads(BEARER.read_text())
    spec["pagination"]["max_pages"] = 3
    a, clock = adapter(spec, paged_handler(calls))
    items = await a.search(Q)
    assert calls == ["1", "2", "3"] and len(items) == 2
    assert len(clock.slept) == 2 and all(s >= 3.0 - 1e-9 for s in clock.slept)  # 3 s/host floor

    def flaky(req):
        if req.url.params["page"] == "2":
            return httpx.Response(500)
        return paged_handler([])(req)

    a2, _ = adapter(spec, flaky)
    assert len(await a2.search(Q)) == 1  # partial results kept


async def test_cursor_pagination():
    spec = json.loads(BEARER.read_text())
    spec["pagination"] = {"style": "cursor", "cursor_param": "after", "next_cursor_path": "meta.next", "max_pages": 3}
    seen = []

    def h(req):
        seen.append(req.url.params.get("after"))
        nxt = None if req.url.params.get("after") == "c2" else ("c2" if req.url.params.get("after") == "c1" else "c1")
        n = len(seen)
        return httpx.Response(200, json={"meta": {"next": nxt}, "data": {"items": [{"product_id": f"c{n}", "name": f"Item {n}x", "pricing": {"min": 1, "max": 2, "currency": "USD"}, "seller": {"id": f"s{n}", "name": f"S{n}"}}]}})

    a, _ = adapter(spec, h)
    assert len(await a.search(Q)) == 3 and seen == [None, "c1", "c2"]


async def test_blocked_unconfigured_killed_and_secret_not_leaked(monkeypatch):
    a, _ = adapter(BEARER, lambda r: httpx.Response(429))
    with pytest.raises(SourceBlocked) as e:
        await a.search(Q)
    assert KEY not in str(e.value) and KEY not in repr(a)
    a, _ = adapter(BEARER, ok(R1), env={})
    assert a.configured() is False
    with pytest.raises(Exception, match="missing"):
        await a.search(Q)
    a, _ = adapter(BEARER, ok(R1), env={"FF_SOURCING_EXAMPLIA_API_KEY": KEY, "FF_SOURCING_EXAMPLIA_DISABLED": "1"})
    with pytest.raises(ProviderDisabled):
        await a.search(Q)
    a, _ = adapter(BEARER, ok(R1), env={"FF_SOURCING_EXAMPLIA_API_KEY": KEY, "FF_SOURCING_KILL_SWITCH": "true"})
    assert (await a.health()).ok is False


def test_interval_floor_and_compliance_text():
    a, _ = adapter(QKEY, ok(R2))
    assert a.limiter.min_interval_s == 5
    spec = json.loads(QKEY.read_text())
    spec["limits"]["min_interval_s"] = 0.1
    a, _ = adapter(spec, ok(R2))
    assert a.limiter.min_interval_s == 3.0
    assert "Robots:" in a.compliance and a.mode == "official_api"


# ---------------- loading / registry / service fallback ----------------
def test_example_refused_unless_allowed(caplog):
    assert load_licensed_adapters(str(BEARER)) == []
    assert "refused" in caplog.text
    assert [a.id for a in load_licensed_adapters(f"{BEARER},{QKEY}", allow_example=True)] == ["examplia_trade", "sinoparts_feed"]
    assert load_licensed_adapters("/nonexistent.json,  ,") == []


def test_registry_loads_but_enables_only_when_listed():
    s = Settings(licensed_mappings=str(BEARER), licensed_allow_example=True)
    reg = build_registry(s)
    assert reg.get("examplia_trade") is not None and not reg.is_enabled("examplia_trade")
    s2 = Settings(licensed_mappings=str(BEARER), licensed_allow_example=True, adapters="examplia_trade")
    assert build_registry(s2).is_enabled("examplia_trade")
    assert build_registry(Settings()).get("examplia_trade") is None


async def test_failure_degrades_to_mock_with_warning():
    a, _ = adapter(BEARER, lambda r: httpx.Response(500))
    reg = AdapterRegistry([MockAdapter(), a], {"examplia_trade"})
    svc = SourcingService(reg, MockTrustClient())
    res = await svc.search(SearchQuery(q="pp granules"))
    st = next(s for s in res.sources if s.source == "examplia_trade")
    assert st.status == "error" and "showing mock results" in (st.warning or "")


# ---------------- quality ----------------
@pytest.mark.parametrize(
    "text,expected",
    [("US $12.5", "USD"), ("RMB 80", "CNY"), ("120 元", "CNY"), ("¥5", "CNY"), ("JP¥500", "JPY"),
     ("eur 9", "EUR"), ("€4", "EUR"), ("£3", "GBP"), ("USDA grade", None), ("", None), ("د.ع 1000", "IQD")],
)
def test_detect_currency(text, expected):
    assert detect_currency(text) == expected


def test_detect_currency_alias_override_and_default():
    assert detect_currency("¥5", {"¥": "JPY"}) == "JPY"
    assert detect_currency("nothing", default="USD") == "USD"


def test_price_sanity():
    D = Decimal
    assert price_is_sane(D(1), D(2))
    assert not price_is_sane(D(0), D(2)) and not price_is_sane(D(-1), D(2)) and not price_is_sane(D(3), D(2))
    assert not price_is_sane(D(1), D(5000)) and not price_is_sane(D(1), D(2), max_price=D(1))
    assert not price_is_sane(D("0.00001"), D("0.00002"))


def _listing(i, title, supplier="Acme Plastics", price="1", images=0, currency="USD"):
    from ff_sourcing.adapters._norm import build_listing

    return build_listing(source="t", native_id=i, title=title, price_min=price, price_max=price,
                         currency=currency, supplier_native_id=supplier, supplier_name=supplier,
                         images=[f"https://x/{n}" for n in range(images)])


def test_title_similarity_order_insensitive():
    assert title_similarity("PP granules virgin", "Virgin PP Granules") == 1.0
    assert title_similarity("Servo motor", "Plastic bottle") < 0.5


def test_dedupe_same_supplier_keeps_best_and_order():
    a = _listing("1", "PP Granules Virgin", images=0)
    b = _listing("2", "virgin pp granules!", images=2)
    c = _listing("3", "PP Granules Virgin", supplier="Other Co")
    d = _listing("4", "PP Granules Virgin", currency="EUR")
    e = _listing("5", "Steel Pipe")
    out = dedupe_listings([a, b, c, d, e])
    assert [x.id for x in out] == ["lst_t_2", "lst_t_3", "lst_t_4", "lst_t_5"]
    assert dedupe_listings([]) == []
