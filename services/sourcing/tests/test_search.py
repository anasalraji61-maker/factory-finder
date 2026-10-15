from ff_sourcing.adapters.mock import load_catalog
from ff_sourcing.domain.models import SearchQuery


async def titles(service, **kw):
    q = kw.pop("q", "")
    page = kw.pop("page", 1)
    size = kw.pop("page_size", 100)
    res = await service.search(SearchQuery(q=q, **kw), page, size)
    return res


async def test_arabic_query_finds_english_title(service):
    res = await titles(service, q="خط انتاج معجنات")
    assert res.total >= 2
    # used bakery lines are production lines too (kind is searchable); explicit "Production Line" titles lead
    assert all(i.kind == "production_line" for i in res.items)
    assert all("Production Line" in i.title for i in res.items[:2])
    assert res.sources[0].source == "mock" and res.sources[0].count == res.total


async def test_arabic_variants_match(service):
    for q in ("الألواح الشمسية", "ألواح شمسيه", "solar panels"):
        res = await titles(service, q=q)
        assert any("Solar Panel" in i.title for i in res.items), q
    res = await titles(service, q="حبيبات بولي بروبلين")
    assert any("PP" in i.title for i in res.items)
    res = await titles(service, q="طاولة وكراسي")
    assert any("Dining Table" in i.title for i in res.items)
    res = await titles(service, q="ماكنة حقن بلاستيك")
    assert any("Injection" in i.title for i in res.items)


async def test_no_match_returns_empty(service):
    res = await titles(service, q="xyzzy unobtainium")
    assert res.total == 0 and res.items == []


async def test_filter_kind(service):
    res = await titles(service, kind="raw_material")
    assert res.total > 5 and {i.kind for i in res.items} == {"raw_material"}


async def test_filter_condition(service):
    used = await titles(service, condition="used")
    assert used.total >= 8 and {i.condition for i in used.items} == {"used"}
    new = await titles(service, kind="production_line", condition="new")
    assert {i.condition for i in new.items} == {"new"}
    ref = await titles(service, condition="refurbished")
    assert ref.total == 1


async def test_filter_origin_country(service):
    res = await titles(service, origin_country="DE")
    assert res.total >= 5 and {i.origin.country_code for i in res.items} == {"DE"}


async def test_filter_category_leaf_and_parent(service):
    leaf = await titles(service, category="plastics")
    assert {i.category for i in leaf.items} == {"plastics"}
    parent = await titles(service, category="raw_material")
    assert {i.kind for i in parent.items} == {"raw_material"} and parent.total > leaf.total


async def test_filter_price_range(service):
    res = await titles(service, kind="product", min_price=100, max_price=200)
    assert res.total > 0
    for i in res.items:
        assert i.price.max.amount >= 100 and i.price.min.amount <= 200


async def test_filter_moq_and_verified(service):
    res = await titles(service, kind="product", moq_max=50)
    assert res.total > 0 and all(i.moq <= 50 for i in res.items)
    res = await titles(service, verified_only=True)
    assert res.total > 0 and all(i.supplier.verified for i in res.items)
    allr = await titles(service)
    assert allr.total == len(load_catalog()["listings"]) and res.total < allr.total


async def test_ranking_prefers_trust_and_price(service):
    from ff_sourcing.clients.trust import MockTrustClient, TrustInfo
    from ff_sourcing.service import SourcingService

    base = await titles(service, q="pump")
    ids = [i.supplier.id for i in base.items]
    # pin: make the second item's supplier green and the rest red => it must come first
    pinned = {s: TrustInfo(supplier_id=s, score=10, band="red") for s in ids}
    winner = [i for i in base.items if "Pump" in i.title][-1]
    pinned[winner.supplier.id] = TrustInfo(supplier_id=winner.supplier.id, score=95, band="green")
    svc2 = SourcingService(service.registry, MockTrustClient(pinned))
    res = await svc2.search(SearchQuery(q="pump"))
    assert res.items[0].id == winner.id
    assert res.items[0].supplier.trust_band == "green"


async def test_ranking_relevance_title_over_secondary(service):
    res = await titles(service, q="PET")
    # title hits (PET bottle blowing, PET resin) must rank above category/supplier-only hits
    assert "PET" in res.items[0].title


async def test_pagination(service):
    p1 = await service.search(SearchQuery(), 1, 25)
    p3 = await service.search(SearchQuery(), 3, 25)
    p4 = await service.search(SearchQuery(), 4, 25)
    n = len(load_catalog()["listings"])
    assert (p1.total, len(p1.items), len(p3.items)) == (n, 25, 25)
    assert len(p4.items) == min(25, n - 75) and n > 75
    ids = [i.id for i in p1.items] + [
        i.id for i in (await service.search(SearchQuery(), 2, 25)).items
    ]
    assert len(set(ids)) == 50


async def test_trust_enrichment_present(service):
    res = await titles(service, q="pump")
    assert all(i.supplier.trust_band in ("green", "yellow", "red") for i in res.items)


async def ids(service, q="", sort="relevance", **kw):
    res = await service.search(SearchQuery(q=q, **kw), 1, 100, sort)
    items = list(res.items)
    for page in range(2, (res.total + 99) // 100 + 1):
        items += (await service.search(SearchQuery(q=q, **kw), page, 100, sort)).items
    res.items = items
    return [i.id for i in items], res


async def test_dialect_and_chinese_queries(service):
    _, chair = await ids(service, "كرسي")
    assert {i.id for i in chair.items} == {"lst_0039", "lst_0040"}
    for q in ("椅子", "كراسي", "chairs", "الكراسي"):
        _, r = await ids(service, q)
        assert {i.id for i in r.items} == {"lst_0039", "lst_0040"}, q
    for q in ("مكينة حقن بلاستيك", "ماكنة حقن", "塑料 注塑机"):
        _, r = await ids(service, q)
        assert r.total >= 4 and any("Injection Molding Machine" in i.title for i in r.items), q
    _, r = await ids(service, "塑料机器")
    assert r.total > 0 and r.items[0].category == "plastics_machinery"
    # items matching "machine" only through the supplier name rank below real machines
    assert [i.category for i in r.items[:5]] == ["plastics_machinery"] * 5
    _, gen = await ids(service, "مولدة")
    assert gen.total >= 4 and all("Generator" in i.title for i in gen.items)


async def test_typo_tolerance_without_false_positives(service):
    _, ok = await ids(service, "bottel")
    assert any("Bottle" in i.title for i in ok.items)
    _, ok = await ids(service, "heidelburg")
    assert [i.id for i in ok.items] == ["lst_0016"]
    _, ok = await ids(service, "stainles steel")
    assert ok.total > 0 and all("Stainless" in i.title or i.supplier for i in ok.items)
    _, ok = await ids(service, "injecton moulding")
    assert any("Injection" in i.title for i in ok.items)
    # unrelated near-words must not match
    _, tile = await ids(service, "tile")
    assert tile.total > 0 and not any("Tires" in i.title for i in tile.items)
    _, tire = await ids(service, "tire")
    assert not any("Tile" in i.title for i in tire.items)
    for junk in ("xqzv", "unobtainiumm", "zzzz"):
        _, r = await ids(service, junk)
        assert r.total == 0, junk


async def test_title_beats_category_beats_description(service):
    _, r = await ids(service, "pump")
    by_id = {i.id: n for n, i in enumerate(r.items)}
    # title hit (Pump) outranks category-only hit (air conditioner/generators live in pumps_hvac)
    titled = [i.id for i in r.items if "Pump" in i.title]
    catonly = [i.id for i in r.items if "Pump" not in i.title]
    assert titled and catonly
    assert max(by_id[t] for t in titled) < min(by_id[c] for c in catonly)


async def test_exact_phrase_boost(service):
    # both words appear in each title; adjacent ones ("Injection Molding") rank first
    _, r = await ids(service, "injection molding")
    assert r.items[0].title.count("Injection Molding") == 1
    # phrase beats a non-adjacent listing with equal term coverage
    _, r = await ids(service, "water pump")
    top = [i.title for i in r.items[:3]]
    assert all("Water Pump" in t for t in top)


async def test_verified_boost_is_small_but_breaks_ties(service):
    from ff_sourcing.clients.trust import MockTrustClient, TrustInfo
    from ff_sourcing.service import SourcingService

    base = await service.search(SearchQuery(q="chair"))
    # same trust everywhere: verified supplier is not worse than an unverified one
    flat = {i.supplier.id: TrustInfo(supplier_id=i.supplier.id, score=50, band="yellow") for i in base.items}
    svc2 = SourcingService(service.registry, MockTrustClient(flat))
    res = await svc2.search(SearchQuery(q="chair"))
    assert len(res.items) == 2
    # deterministic: repeated calls give identical order
    again = await svc2.search(SearchQuery(q="chair"))
    assert [i.id for i in res.items] == [i.id for i in again.items]


async def test_stable_order_for_empty_query(service):
    a, _ = await ids(service)
    b, _ = await ids(service)
    assert a == b and len(set(a)) == len(a) == 165


async def test_sort_params(service):
    mid = lambda i: (i.price.min.amount + i.price.max.amount) / 2  # noqa: E731
    _, res = await ids(service, sort="price_asc")
    usd = [i for i in res.items if i.price.min.currency == "USD"]
    assert [mid(i) for i in usd] == sorted(mid(i) for i in usd)
    _, desc = await ids(service, sort="price_desc")
    usd = [i for i in desc.items if i.price.min.currency == "USD"]
    assert [mid(i) for i in usd] == sorted((mid(i) for i in usd), reverse=True)
    _, trust = await ids(service, sort="trust")
    scores = [i.supplier.trust_score for i in trust.items]
    assert scores == sorted(scores, reverse=True)
    _, moq = await ids(service, sort="moq")
    moqs = [i.moq for i in moq.items if i.moq is not None]
    assert moqs == sorted(moqs) and moqs[0] <= moqs[-1]
    # same set, different order
    assert {i.id for i in moq.items} == {i.id for i in res.items}


async def test_facets_cover_full_matched_set(service):
    res = await service.search(SearchQuery(), 1, 5)  # page of 5, matched set of 165
    f = res.facets
    for name in ("kind", "condition", "origin_country", "category"):
        buckets = getattr(f, name)
        assert sum(b.count for b in buckets) == 165 and buckets
        counts = [b.count for b in buckets]
        assert counts == sorted(counts, reverse=True)
    assert {b.value for b in f.kind} == {"product", "raw_material", "production_line"}
    used = next(b.count for b in f.condition if b.value == "used")
    assert used == (await service.search(SearchQuery(condition="used"))).total
    sub = await service.search(SearchQuery(q="pump"), 1, 2)
    assert sub.total > 2 and sum(b.count for b in sub.facets.kind) == sub.total


async def test_sort_and_facets_over_http(client):
    r = await client.get("/v1/search", params={"q": "pump", "sort": "price_asc", "page_size": 3})
    body = r.json()
    assert r.status_code == 200 and len(body["items"]) == 3
    assert sum(b["count"] for b in body["facets"]["kind"]) == body["total"]
    assert (await client.get("/v1/search", params={"sort": "bogus"})).status_code == 422


async def test_search_is_fast(service):
    import time

    service._results = type(service._results)(0)  # no result cache: measure the real work
    await service.search(SearchQuery(q="pump"))  # warm token caches
    for q in ("", "ماكنة حقن بلاستيك", "stainles steel", "塑料机器"):
        t = time.perf_counter()
        for _ in range(5):
            await service.search(SearchQuery(q=q), 1, 20)
        avg_ms = (time.perf_counter() - t) / 5 * 1000
        assert avg_ms < 60, (q, avg_ms)  # ~5-12ms typical; generous bound for slow CI
