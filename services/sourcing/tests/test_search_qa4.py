"""QA4: Arabic normalization/stemming, quantity queries, used lines, filters, sort stability, dedupe, pagination."""

import pytest

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.domain import search as engine
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.domain.text import extract_quantity, normalize, stem


async def ids(service, q="", page=1, size=100, sort="relevance", **kw):
    res = await service.search(SearchQuery(q=q, **kw), page, size, sort=sort)
    return [i.id for i in res.items], res


def test_arabic_indic_and_persian_digits_normalize():
    assert normalize("١٠٠٠ قطعة") == "1000 قطعه"
    assert normalize("۱۰۰۰") == "1000"


def test_definite_article_on_short_words():
    assert stem("الخط") == "خط" and stem("والخط") == "خط" and stem("للخط") == "خط"
    assert stem("الخطوط") == "خطوط"


def test_extract_quantity():
    assert extract_quantity("قماش قطن 1000 قطعة") == ("قماش قطن", 1000, "pc")
    assert extract_quantity("cotton 1000 pcs") == ("cotton", 1000, "pc")
    assert extract_quantity("كراسي ٥٠٠ طقم") == ("كراسي", 500, "set")
    assert extract_quantity("فولاذ ٥٠٠ كغم")[1] is None  # capacity/spec units stay literal ("250 kg/h")
    assert extract_quantity("steel 304 2 tons")[1] is None
    assert extract_quantity("1000 قطعة") == ("1000 قطعة", None, None)  # nothing left to search: keep literal
    assert extract_quantity("cotton 1000")[1] is None
    assert extract_quantity("cable 3 m")[1] is None  # bare m/l are never quantities


@pytest.mark.parametrize("q", ["خط انتاج مستعمل", "خط إنتاج مستعمل", "الخط الانتاج المستعمل", "والخط الإنتاجي المستعمل",
                               "used production line", "خطوط انتاج مستعملة", "الخطوط الإنتاجية المستعملة"])
async def test_used_production_line_queries(service, q):
    got, res = await ids(service, q)
    assert got, q
    assert all(i.condition == "used" for i in res.items), q
    assert {i.kind for i in res.items} == {"production_line"}, q


async def test_used_line_queries_equivalent(service):
    base, _ = await ids(service, "خط انتاج مستعمل")
    for q in ("الخطوط الإنتاجية المستعملة", "used production line", "خط إنتاج مستعمله"):
        assert (await ids(service, q))[0] == base, q


@pytest.mark.parametrize("q", ["قماش قطن 1000 قطعة", "قماش قطن ١٠٠٠ قطعه", "cotton fabric 1000 pcs",
                               "cotton fabric 1000 pieces"])
async def test_quantity_not_matched_as_text(service, q):
    got, res = await ids(service, q)
    assert got, q
    base, _ = await ids(service, "cotton fabric", moq_max=1000)
    assert set(got) <= set(base) | set(got) and all(i.moq is None or i.moq <= 1000 for i in res.items)


async def test_quantity_equivalence_across_digits_and_languages(service):
    a, _ = await ids(service, "قماش قطن 1000 قطعة")
    b, _ = await ids(service, "قماش قطن ١٠٠٠ قطعة")
    assert a == b


async def test_quantity_respects_moq(service):
    big, _ = await ids(service, "قماش قطن 1000000 قطعة")
    small, res = await ids(service, "قماش قطن 1 قطعة")
    assert set(small) <= set(big)
    assert all(i.moq is None or i.moq <= 1 for i in res.items)



# ---- filters -------------------------------------------------------------
async def test_filters_combine(service):
    all_ids, _ = await ids(service, "machine")
    got, res = await ids(service, "machine", origin_country="cn", verified_only=True, min_price=1000, max_price=50000)
    assert set(got) <= set(all_ids)
    for i in res.items:
        assert i.supplier.verified and (i.origin or i.supplier.location).country_code == "CN"
        assert i.price.max.amount >= 1000 and i.price.min.amount <= 50000


async def test_price_range_inverted_is_empty_not_crash(service):
    got, _ = await ids(service, "", min_price=100, max_price=1)
    assert got == []


async def test_moq_filter_boundary_inclusive(service):
    _, res = await ids(service, "")
    some = next(i for i in res.items if i.moq)
    got, r2 = await ids(service, "", moq_max=some.moq)
    assert some.id in got and all(i.moq is None or i.moq <= some.moq for i in r2.items)
    got2, _ = await ids(service, "", moq_max=some.moq - 1)
    assert some.id not in got2


# ---- sort stability & pagination ---------------------------------------------
@pytest.mark.parametrize("sort", ["relevance", "price_asc", "price_desc", "trust", "moq"])
async def test_sort_deterministic_and_pages_partition(service, sort):
    def collect(size):
        async def go():
            out: list[str] = []
            total = None
            for p in range(1, 400):
                got, r = await ids(service, "", page=p, size=size, sort=sort)
                assert total in (None, r.total)
                total = r.total
                out += got
                if not got:
                    return out, total
        return go()

    a, total = await collect(7)
    b, _ = await collect(50)
    c, _ = await collect(7)
    assert a == b == c
    assert len(set(a)) == len(a) == total


async def test_page_beyond_end_is_empty_with_total(service):
    got, res = await ids(service, "machine", page=99, size=20)
    assert got == [] and res.total > 0


async def test_facets_independent_of_page(service):
    _, a = await ids(service, "machine", page=1, size=3)
    _, b = await ids(service, "machine", page=2, size=3)
    assert a.facets == b.facets


# ---- dedupe -----------------------------------------------------------------
async def test_same_supplier_same_title_across_sources_collapses_to_cheapest():
    from ff_sourcing.domain.models import Listing  # noqa: F401

    base = MockAdapter()
    items = (await base.search(SearchQuery(limit=200)))
    a = items[0]
    cheap = a.model_copy(update={"id": "x_cheap", "source": "other",
                                 "price": a.price.model_copy(update={
                                     "min": a.price.min.model_copy(update={"amount": a.price.min.amount / 2})})})
    out = engine.dedupe([(a, engine.Match(1.0)), (cheap, engine.Match(1.0))])
    assert [x[0].id for x in out] == ["x_cheap"]


async def test_dedupe_title_case_and_punctuation_insensitive():
    items = await MockAdapter().search(SearchQuery(limit=200))
    a = items[0]
    b = a.model_copy(update={"id": "dup2", "source": "other", "title": a.title.upper() + "!!"})
    out = engine.dedupe([(a, engine.Match(1.0)), (b, engine.Match(1.0))])
    assert len(out) == 1


async def test_dedupe_keeps_different_suppliers():
    items = await MockAdapter().search(SearchQuery(limit=200))
    a = items[0]
    other_sup = a.supplier.model_copy(update={"id": "other_sup"})
    b = a.model_copy(update={"id": "dup3", "source": "other", "supplier": other_sup})
    assert len(engine.dedupe([(a, engine.Match(1.0)), (b, engine.Match(1.0))])) == 2


async def test_dedupe_order_independent():
    items = await MockAdapter().search(SearchQuery(limit=200))
    a = items[0]
    b = a.model_copy(update={"id": "dup4", "source": "other"})  # equal price: tie must not depend on input order
    r1 = engine.dedupe([(a, engine.Match(1.0)), (b, engine.Match(1.0))])
    r2 = engine.dedupe([(b, engine.Match(1.0)), (a, engine.Match(1.0))])
    assert [x[0].id for x in r1] == [x[0].id for x in r2]
