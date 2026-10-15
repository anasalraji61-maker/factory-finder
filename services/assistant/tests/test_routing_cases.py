"""Runs the deterministic routing eval set (fixtures/routing_cases.json) through parser + mock assistant."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ff_assistant.clients import build_mock_clients
from ff_assistant.config import Settings
from ff_assistant.domain.parser import parse
from ff_assistant.service import Assistant

_DATA = json.loads((Path(__file__).parent / "fixtures" / "routing_cases.json").read_text(encoding="utf-8"))
CASES = _DATA["cases"]
INJECTION_WARNING = "prompt_injection_ignored"


def check(case: dict) -> list[str]:
    exp = case["expect"]
    p = parse(case["text"])
    bad: list[str] = []
    got = {
        "intent": p.intent.value,
        "dest_city": p.destination.city if p.destination else None,
        "dest_cc": p.destination.country_code if p.destination else None,
        "origin_cc": p.origin.country_code if p.origin else None,
        "quantity": p.quantity,
        "unit": p.unit,
        "reference": p.reference,
        "reference_type": p.reference_type,
        "supplier_id": p.supplier_id,
        "deal_id": p.deal_id,
        "hs_code": p.hs_code,
        "incoterm": p.incoterm.value if p.incoterm else None,
        "listing_ids": p.listing_ids,
        "condition": p.condition.value if p.condition else None,
        "kind": p.kind.value if p.kind else None,
    }
    for key, want in exp.items():
        if key == "injection":
            continue
        have = got[key]
        if key == "quantity" and want is not None and have is not None:
            ok = Decimal(want) == have
        else:
            ok = have == want
        if not ok:
            bad.append(f"{key}: expected {want!r}, got {have!r}")
    res = asyncio.run(Assistant(build_mock_clients(), Settings(clients="mock")).handle(case["text"]))
    if res.intent.value != exp["intent"]:
        bad.append(f"assistant intent: expected {exp['intent']!r}, got {res.intent.value!r}")
    flagged = INJECTION_WARNING in res.warnings
    if exp.get("injection", False) != flagged:
        bad.append(f"injection flag: expected {exp.get('injection', False)}, got {flagged}")
    if exp.get("injection") and (res.listings or res.quote or res.trust or res.cards):
        bad.append("injection attempt triggered a tool/search result")
    return bad


def test_fixture_size_and_coverage():
    assert len(CASES) >= 80
    assert len({c["id"] for c in CASES}) == len(CASES)
    cats = {c["category"] for c in CASES}
    assert {"search", "quote", "compare", "trust", "hs", "track", "deal", "compliance", "smalltalk", "out_of_scope", "injection"} <= cats
    assert any(c["text"].isascii() for c in CASES) and any(not c["text"].isascii() for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_routing_case(case):
    assert check(case) == [], case["text"]


def test_routing_accuracy_is_total():
    failed = [c["id"] for c in CASES if check(c)]
    assert not failed, f"{len(CASES) - len(failed)}/{len(CASES)} correct; failing: {failed}"
