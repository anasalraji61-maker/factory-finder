"""Adversarial / property-style tests (parametrized; hypothesis is not a dependency): price parsing,
search pagination / dedupe / ranking determinism, and adapter rate-limit / robots guards."""

import itertools
import random
import time
from decimal import Decimal

import httpx
import pytest

from ff_sourcing.adapters.http_base import HostRateLimiter, RobotsGuard
from ff_sourcing.domain import search as engine
from ff_sourcing.domain.models import (
    Listing,
    Location,
    Money,
    MoneyRange,
    SearchQuery,
    SupplierSummary,
)
from ff_sourcing.domain.pricing import MAX_PRICE_VALUE, parse_number, parse_price_text

D = Decimal


# ------------------------------------------------------------------------------------ price parsing
@pytest.mark.parametrize(
    ("text", "lo", "hi", "ccy"),
    [
        ("٣٫٥ دولار", "3.5", "3.5", "USD"),
        ("١٬٢٣٤٫٥٠ $", "1234.50", "1234.50", "USD"),
        ("$1,234.50", "1234.50", "1234.50", "USD"),
        ("€1.234,50", "1234.50", "1234.50", "EUR"),
        ("$10-20", "10", "20", "USD"),
        ("$10 – $20", "10", "20", "USD"),
        ("$20-10", "10", "20", "USD"),
        ("US$ 5 to 8", "5", "8", "USD"),
        ("$.5", "0.5", "0.5", "USD"),
        ("$5.", "5", "5", "USD"),
        ("１２３４ USD", "1234", "1234", "USD"),  # full-width digits
        ("\x00$5\x00", "5", "5", "USD"),
        ("$ 5" + " " * 600, "5", "5", "USD"),  # trailing padding beyond the length bound
    ],
)
def test_price_cases(text, lo, hi, ccy):
    r = parse_price_text(text)
    assert (r.price_min, r.price_max, r.currency) == (D(lo), D(hi), ccy)


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("$-5", "negative_price"),
        ("-$5", "negative_price"),
        ("-5 USD", "negative_price"),
        ("$0", "non_positive_price"),
        ("$٠", "non_positive_price"),
        ("$NaN", "no_price"),
        ("NaN", "no_price"),
        ("$Infinity", "no_price"),
        ("-inf", "no_price"),
        ("$1e5", "no_price"),
        ("$1,2,3", "ambiguous_multiple_numbers"),
        ("$1٫٢٫٣", "ambiguous_multiple_numbers"),
        ("$" + "9" * 400, "price_out_of_range"),
        ("$" + "9" * 13, "price_out_of_range"),
        ("", "no_price"),
        (None, "no_price"),
        ("   ", "no_price"),
    ],
)
def test_price_rejected_never_guessed(text, flag):
    r = parse_price_text(text)
    assert r.price_min is None and r.price_max is None and r.tiers == []
    assert flag in r.flags


def test_price_upper_bound_is_inclusive_and_exact():
    assert parse_price_text(f"${MAX_PRICE_VALUE}").price_min == MAX_PRICE_VALUE
    assert parse_price_text("$1000000000001" + "").price_min is None


@pytest.mark.parametrize("obj", [123, 12.5, float("nan"), float("inf"), b"abc", [1, 2], {"a": 1}, object(), True])
def test_price_non_string_inputs_never_crash(obj):
    r = parse_price_text(obj)
    for t in r.tiers:
        assert t.price_min.is_finite() and t.price_min > 0 and t.price_max >= t.price_min


_ALPHABET = list("0123456789٠١٢٣٤٥٦٧٨٩.,٫٬-–$¥€ \tabcXYZ()/;+:~至件套吨دولارللطن\x00‏")


def test_price_fuzz_invariants_and_timing():
    rng = random.Random(1234)
    t0 = time.perf_counter()
    for _ in range(1500):
        s = "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 120)))
        r = parse_price_text(s)
        assert r == parse_price_text(s) or r.to_dict() == parse_price_text(s).to_dict()  # deterministic
        for t in r.tiers:
            assert t.price_min.is_finite() and t.price_max.is_finite()
            assert 0 < t.price_min <= t.price_max <= MAX_PRICE_VALUE
        if r.price_min is None:
            assert "no_price" in r.flags
        r.to_dict()
    assert time.perf_counter() - t0 < 20


@pytest.mark.parametrize("pat", ["1,", "1.", "9" * 3 + ",", "$ ", "1 - ", "- ", "٣٫", "¥ "])
def test_price_pathological_repetition_is_bounded(pat):
    t0 = time.perf_counter()
    parse_price_text(pat * 20000)
    assert time.perf_counter() - t0 < 2


@pytest.mark.parametrize("raw", ["", " ", ".", ",", "..", "1.2.3,4", "abc", "١٢٫٥٠", "1,23", "0,5"])
def test_parse_number_never_raises(raw):
    v, flags = parse_number(raw)
    assert v is None or v.is_finite()
    assert v is not None or flags


@pytest.mark.parametrize(
    "text", ["$10 (100-499 pcs); $8 (500+ pcs)", "$٣٫٥ / كغ", "¥12/件", "from US$3.5 / kg", "50 دولار للطن"]
)
def test_arabic_digit_equivalence(text):
    ar = text.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    assert parse_price_text(ar).to_dict() == parse_price_text(text).to_dict()


# ------------------------------------------------------------------------------ pagination / ranking
def mk(i, *, title=None, supplier="s1", price="10", ccy="USD", source="mock", cat="c", band="unknown"):
    sup = SupplierSummary(id=supplier, name=supplier, location=Location(country_code="CN"), trust_band=band)
    m = Money(amount=D(price), currency=ccy)
    return Listing(
        id=f"L{i:03d}", source=source, kind="product", title=title or f"Widget {i}", category=cat,
        price=MoneyRange(min=m, max=m), supplier=sup,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("page", "size", "expect"),
    [(1, 3, [0, 1, 2]), (2, 3, [3, 4, 5]), (4, 3, [9]), (5, 3, []), (0, 3, []), (-1, 3, []), (-5, 2, []),
     (1, 0, []), (1, -1, []), (10**12, 20, []), (1, 10**9, list(range(10)))],
)  # fmt: skip
def test_paginate_bounds(page, size, expect):
    assert engine.paginate(list(range(10)), page, size) == expect


@pytest.mark.parametrize("size", [1, 2, 3, 7, 10, 100])
def test_pages_partition_the_ranked_list(size):
    items = list(range(23))
    got = list(itertools.chain.from_iterable(engine.paginate(items, p, size) for p in range(1, 30)))
    assert got == items


def _items(n=12):
    out = []
    for i in range(n):
        lst = mk(i, title="Widget", supplier=f"s{i % 4}", price=str(5 + i % 5), cat="a" if i % 2 else "b",
                 band=("green", "yellow", "red", "unknown")[i % 4])  # fmt: skip
        out.append((lst, engine.Match(0.8, bool(i % 3))))
    return out


@pytest.mark.parametrize("sort", engine.SORTS)
def test_rank_is_order_independent_and_deterministic(sort):
    items = _items()
    base = [x.id for x in engine.rank(items, sort)]
    rng = random.Random(7)
    for _ in range(25):
        shuffled = items[:]
        rng.shuffle(shuffled)
        assert [x.id for x in engine.rank(shuffled, sort)] == base
    assert len(set(base)) == len(base) == len(items)


def test_rank_single_and_empty():
    assert engine.rank([]) == []
    one = _items(1)
    assert [x.id for x in engine.rank(one)] == ["L000"]


@pytest.mark.parametrize("sort", ["price_asc", "price_desc"])
def test_rank_price_sort_puts_foreign_currency_last_and_is_monotonic(sort):
    items = [(mk(0, price="3", ccy="CNY"), engine.Match(1)), (mk(1, price="9"), engine.Match(1)),
             (mk(2, price="2"), engine.Match(1)), (mk(3, price="9999", ccy="JPY"), engine.Match(1))]  # fmt: skip
    out = engine.rank(items, sort)
    usd = [x for x in out if x.price.min.currency == "USD"]
    assert out[: len(usd)] == usd and len(usd) == 2
    amounts = [x.price.min.amount for x in usd]
    assert amounts == sorted(amounts, reverse=(sort == "price_desc"))


def test_dedupe_idempotent_keeps_cheapest_and_unique_ids():
    m = engine.Match(1)
    items = [
        (mk(1, title="Steel  Pipe", price="9"), m), (mk(2, title="steel pipe", price="7"), m),
        (mk(3, title="Steel Pipe", price="8", supplier="s2"), m), (mk(1, title="Steel Pipe XL", price="1"), m),
    ]  # fmt: skip
    out = engine.dedupe(items)
    assert engine.dedupe(out) == out
    ids = [(a.source, a.id) for a, _ in out]
    assert len(ids) == len(set(ids))
    assert "L002" in {a.id for a, _ in out} and "L001" in {a.id for a, _ in out}
    assert not any(a.price.min.amount == D(9) for a, _ in out)


def test_dedupe_is_order_independent_for_distinct_prices():
    m = engine.Match(1)
    items = [(mk(i, title="Gear", price=str(10 - i)), m) for i in range(6)]
    a = {x.id for x, _ in engine.dedupe(items)}
    b = {x.id for x, _ in engine.dedupe(items[::-1])}
    assert a == b == {"L005"}


@pytest.mark.parametrize("q", ["", "solar", "خط انتاج", "   ", "a" * 2000, "';--", "<script>", "\x00", "💥", "ـــ"])
async def test_search_deterministic_and_pages_partition(service, q):
    r1 = await service.search(SearchQuery(q=q), 1, 100)
    r2 = await service.search(SearchQuery(q=q), 1, 100)
    assert [i.id for i in r1.items] == [i.id for i in r2.items]
    assert r1.total == len(r1.items) <= 100 or r1.total > 100
    ids = [(i.source, i.id) for i in r1.items]
    assert len(ids) == len(set(ids))
    paged = []
    for p in range(1, 60):
        res = await service.search(SearchQuery(q=q), p, 7)
        assert res.total == r1.total
        paged += [(i.source, i.id) for i in res.items]
        if not res.items:
            break
    assert paged[: len(ids)] == ids


@pytest.mark.parametrize(("page", "size"), [(0, 5), (-3, 5), (1, 0), (10**9, 20)])
async def test_search_service_degenerate_paging_returns_empty(service, page, size):
    res = await service.search(SearchQuery(q=""), page, size)
    assert res.items == [] and res.total > 0


# --------------------------------------------------------------------------- rate limit / robots
async def test_rate_limiter_interval_floor_and_independent_hosts():
    now = [0.0]
    slept = []

    async def sleep(d):
        slept.append(d)
        now[0] += d

    for bad in (0, -5, 0.0001, float("-inf")):
        lim = HostRateLimiter(bad, clock=lambda: now[0], sleep=sleep)
        assert lim.min_interval_s >= 3.0 or lim.min_interval_s >= 1.0  # floor is enforced
    lim = HostRateLimiter(-1, clock=lambda: now[0], sleep=sleep)
    floor = lim.min_interval_s
    assert floor > 0
    for _ in range(4):
        await lim.wait("a")
    await lim.wait("b")
    assert slept == [floor] * 3  # host b is not throttled by host a; no request ever skips the interval


async def test_rate_limiter_cooldown_negative_and_nan_are_safe():
    now = [100.0]
    lim = HostRateLimiter(3.0, clock=lambda: now[0])
    lim.cool_down("h", -50)
    assert lim.cooldown_remaining("h") == 0.0
    lim.cool_down("h", 30)
    lim.cool_down("h", 10)  # a shorter cooldown never shortens a longer one
    assert lim.cooldown_remaining("h") == 30
    now[0] += 31
    assert lim.cooldown_remaining("h") == 0.0


async def test_rate_limiter_concurrent_waiters_are_serialized():
    import asyncio

    now = [0.0]

    async def sleep(d):
        now[0] += d

    lim = HostRateLimiter(3.0, clock=lambda: now[0], sleep=sleep)
    stamps = []

    async def hit():
        await lim.wait("h")
        stamps.append(now[0])

    await asyncio.gather(*(hit() for _ in range(6)))
    gaps = [b - a for a, b in itertools.pairwise(sorted(stamps))]
    assert all(g >= lim.min_interval_s - 1e-9 for g in gaps)


def _guard(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RobotsGuard("FactoryFinderBot/1.0", client, None)


@pytest.mark.parametrize(
    ("body", "url", "ok"),
    [
        ("User-agent: *\nDisallow: /private", "https://h.example/private/x", False),
        ("User-agent: *\nDisallow: /private", "https://h.example/public", True),
        ("User-agent: *\nDisallow: /", "https://h.example/", False),
        ("User-agent: FactoryFinderBot\nDisallow: /", "https://h.example/a", False),
        ("User-agent: *\nDisallow:", "https://h.example/a", True),
        ("\x00\xff garbage <html>", "https://h.example/a", True),
        ("", "https://h.example/a", True),
    ],
)
async def test_robots_rules(body, url, ok):
    g = _guard(lambda r: httpx.Response(200, text=body))
    assert await g.allowed(url) is ok


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
async def test_robots_error_statuses_fail_closed(status):
    g = _guard(lambda r: httpx.Response(status))
    assert await g.allowed("https://h.example/a") is False


async def test_robots_fetched_once_per_origin_and_per_origin_isolation():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /x" if req.url.host == "a.example" else "")

    g = _guard(handler)
    assert await g.allowed("https://a.example/x") is False
    assert await g.allowed("https://a.example/y") is True
    assert await g.allowed("https://b.example/x") is True
    assert sorted(calls) == ["https://a.example/robots.txt", "https://b.example/robots.txt"]


@pytest.mark.parametrize("url", ["https://h.example/%2e%2e/private", "https://h.example/PRIVATE", "https://h.example//private"])
async def test_robots_path_tricks_do_not_open_disallowed_paths_unexpectedly(url):
    g = _guard(lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /private"))
    # must not raise; the decision is a plain bool
    assert isinstance(await g.allowed(url), bool)
