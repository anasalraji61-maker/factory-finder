"""Relevance regression suite: realistic bilingual buyer queries against the mock catalog.

Fixture: tests/fixtures/relevance_cases.json (see its ``_doc``). Findings: docs/decisions/sourcing-relevance-qa.md.
"""

import json
from pathlib import Path

import pytest

from ff_sourcing.domain.models import SearchQuery

FIX = json.loads((Path(__file__).parent / "fixtures" / "relevance_cases.json").read_text(encoding="utf-8"))
CASES = FIX["cases"]


def _label(c):
    extra = {k: v for k, v in c.items() if k in ("kind", "condition", "moq_max", "sort")}
    return f"{c['q']}|{extra}" if extra else c["q"]


async def _run(service, c, size=100):
    kw = {k: c[k] for k in ("kind", "condition", "moq_max") if k in c}
    return await service.search(SearchQuery(q=c["q"], **kw), 1, size, sort=c.get("sort", "relevance"))


def test_fixture_has_at_least_60_distinct_queries():
    assert len({c["q"] for c in CASES}) >= 60


@pytest.mark.parametrize("case", CASES, ids=[_label(c) for c in CASES])
async def test_relevance_case(service, case):
    res = await _run(service, case)
    ids = [i.id for i in res.items]
    if "total" in case:
        assert res.total == case["total"], ids
    if "top1" in case:
        assert ids and ids[0] == case["top1"], ids[:5]
    for want in case.get("in_top5", []):
        assert want in ids[:5], (want, ids[:5])
    if "all_kind" in case:
        assert res.items and {i.kind for i in res.items} == {case["all_kind"]}
    if "all_condition" in case:
        assert res.items and {i.condition for i in res.items} == {case["all_condition"]}
    if "max_moq" in case:
        assert res.items and all(i.moq is None or i.moq <= case["max_moq"] for i in res.items)
    order = case.get("sorted_by")
    if order in ("price_asc", "price_desc"):
        mids = [(i.price.min.amount + i.price.max.amount) / 2 for i in res.items if i.price.min.currency == "USD"]
        assert mids == sorted(mids, reverse=order == "price_desc") and len(mids) > 1
    if order == "moq":
        moqs = [i.moq for i in res.items if i.moq is not None]
        assert moqs == sorted(moqs) and len(moqs) > 1


@pytest.mark.parametrize("group", FIX["equivalent_queries"], ids=lambda g: g[0])
async def test_spelling_variants_return_identical_results(service, group):
    results = []
    for q in group:
        res = await service.search(SearchQuery(q=q), 1, 100)
        results.append([i.id for i in res.items])
    assert results[0], group
    assert all(r == results[0] for r in results), dict(zip(group, results, strict=True))


async def test_ambiguous_daqiq_prefers_flour_over_precision(service):
    res = await service.search(SearchQuery(q="دقيق"), 1, 100)
    ids = [i.id for i in res.items]
    assert "lst_0079" not in ids and ids[:2] and set(ids) == {"lst_0012", "lst_0023"}


async def test_category_siblings_pruned_but_head_category_word_kept(service):
    ac = await service.search(SearchQuery(q="مكيف"), 1, 100)
    assert [i.id for i in ac.items] == ["lst_0057"]
    pumps = await service.search(SearchQuery(q="pump"), 1, 100)
    assert len(pumps.items) > 5  # "pump" is the head of "Pumps & air conditioning": siblings stay


async def test_search_latency_p95_regression(service):
    import time

    qs = [c["q"] for c in CASES] + [q for g in FIX["equivalent_queries"] for q in g]
    qs = (qs * (200 // len(qs) + 1))[:200]
    assert len(qs) == 200
    await service.search(SearchQuery(q="warmup"), 1, 20)
    times = []
    for q in qs:
        t0 = time.perf_counter()
        await service.search(SearchQuery(q=q), 1, 20)
        times.append(time.perf_counter() - t0)
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    # generous bound (typically a few ms): only catches order-of-magnitude regressions, stays stable on slow CI
    assert p95 < 0.5, f"p95 search latency {p95 * 1000:.1f} ms"
