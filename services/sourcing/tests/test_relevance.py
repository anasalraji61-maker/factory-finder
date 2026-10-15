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
