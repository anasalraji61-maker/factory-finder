"""Runs the deterministic routing eval set (fixtures/routing_cases.json) through parser + mock assistant."""

import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from ff_assistant.clients import build_mock_clients
from ff_assistant.compose import help_text
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
        if key in ("injection", "message_blocked", "numeric_guard"):
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
    blocked = "private_message_blocked" in res.warnings
    if exp.get("message_blocked", False) != blocked:
        bad.append(f"message_blocked: expected {exp.get('message_blocked', False)}, got {blocked}")
    if blocked and (res.listings or res.quote or res.trust or res.cards):
        bad.append("private-message request triggered a tool/search result")
    bad += numeric_violations(case["text"], res)  # every case: answers never invent numbers
    return bad


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
SCALE_CONSTANTS = {Decimal(100)}  # the "/100" of a trust score


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text.translate(_ARABIC_DIGITS))}


def numeric_violations(user_text: str, res) -> list[str]:
    """Numbers in the answer must come from tool output (the structured result) or the user's own message."""
    if res.answer_text in (help_text("ar"), help_text("en")):  # static template examples
        return []
    allowed = _numbers(user_text) | _numbers(res.model_dump_json(exclude={"answer_text"})) | SCALE_CONSTANTS
    allowed |= {a.to_integral_value() for a in allowed}  # displayed rounded ("4 $" for 4.00 / 3.6)
    allowed |= {a.to_integral_value(rounding="ROUND_DOWN") for a in allowed}
    extra = sorted(str(n) for n in _numbers(res.answer_text) - allowed)
    return [f"answer numbers not from tool output: {extra}"] if extra else []


def test_fixture_size_and_coverage():
    assert len(CASES) >= 165
    assert len({c["id"] for c in CASES}) == len(CASES)
    cats = {c["category"] for c in CASES}
    assert {"search", "quote", "compare", "trust", "hs", "track", "deal", "compliance", "smalltalk", "out_of_scope", "injection", "rfq", "message", "duties", "ambiguity", "numeric"} <= cats
    assert any(c["text"].isascii() for c in CASES) and any(not c["text"].isascii() for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_routing_case(case):
    assert check(case) == [], case["text"]


def test_routing_accuracy_is_total():
    failed = [c["id"] for c in CASES if check(c)]
    assert not failed, f"{len(CASES) - len(failed)}/{len(CASES)} correct; failing: {failed}"


# -- QA wave 4: read-only tools and estimate labelling --------------------------------------------------------
_ESTIMATE_MARKERS = ("estimate", "indicative", "تقدير", "تقريب", "استرشاد", "~", "أكّد", "confirm")
_PRICE_RE = re.compile(r"(?:\$|USD|IQD|CNY|EUR|دولار)")


def test_clients_expose_no_write_operations():
    import inspect

    from ff_assistant.clients import base

    verbs = ("create", "update", "delete", "post", "send", "pay", "confirm", "cancel", "set_", "add_", "remove")
    names = [
        n for proto in vars(base).values() if inspect.isclass(proto) and proto.__module__ == base.__name__
        for n, fn in vars(proto).items() if inspect.iscoroutinefunction(fn) or inspect.isfunction(fn)
    ]
    assert names, "client protocols not found"
    offenders = [n for n in names if n.lstrip("_").startswith(verbs)]
    assert not offenders, f"assistant clients must be read-only, found: {offenders}"


def test_mock_clients_record_only_reads():
    clients = build_mock_clients()
    asyncio.run(Assistant(clients, Settings(clients="mock")).handle("ارسل رسالة خاصة للمورد sup_cn_001 وكله اني اريد خصم"))
    asyncio.run(Assistant(clients, Settings(clients="mock")).handle("اريد انشر طلب شراء ٥ اطنان قماش واستلم عروض"))
    # drafting an RFQ / refusing a message must not have touched any service
    for c in vars(clients).values():
        assert not getattr(c, "calls", [])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_prices_are_labelled_as_estimates(case):
    res = asyncio.run(Assistant(build_mock_clients(), Settings(clients="mock")).handle(case["text"], user_id="u_1"))
    if res.intent.value == "deal_status":
        return  # a recorded deal amount is a fact held by the deals service, shown under its own label
    if _PRICE_RE.search(res.answer_text):
        low = res.answer_text.lower()
        assert any(m.lower() in low for m in _ESTIMATE_MARKERS), res.answer_text
