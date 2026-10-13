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
    assert all("Production Line" in i.title for i in res.items)
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
