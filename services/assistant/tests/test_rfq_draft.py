import asyncio

from ff_assistant.clients import build_mock_clients
from ff_assistant.config import Settings
from ff_assistant.service import Assistant


def run(text, **kw):
    return asyncio.run(Assistant(build_mock_clients(), Settings(clients="mock")).handle(text, **kw))


def rows(res):
    return {r.key: r for r in res.cards[0].rows}


def test_arabic_complete_draft():
    res = run("انشر طلب شراء ٥ اطنان قماش قطن الى بغداد بسعر 3 دولار")
    assert res.intent.value == "create_rfq_draft"
    c = res.cards[0]
    assert c.type.value == "rfq_draft" and c.refs["deep_link"] == "/requests/new" and c.refs["missing"] == ""
    r = rows(res)
    assert r["quantity"].value == "5" and r["unit"].value == "ton" and r["destination"].value_ar
    assert r["target_price"].value == "3 USD" and r["product"].value
    assert not (res.listings or res.quote or res.trust)


def test_english_complete_draft():
    res = run("post a purchase request for 2000 kg of cotton delivered to Basra, target price 4 USD")
    assert res.intent.value == "create_rfq_draft"
    r = rows(res)
    assert r["quantity"].value == "2000" and r["unit"].value == "kg" and r["destination"].value
    assert r["target_price"].value == "4 USD"
    assert res.cards[0].refs["missing"] == ""


def test_missing_fields_listed_ar_and_en():
    res = run("انشر طلب شراء قماش")
    assert res.cards[0].refs["missing"] == "quantity,destination"
    assert res.cards[0].severity == "warning" and "الكمية" in res.answer_text
    assert rows(res)["quantity"].value is None and rows(res)["target_price"].value is None
    res = run("create an RFQ")
    assert set(res.cards[0].refs["missing"].split(",")) == {"product", "quantity", "destination"}
    assert "missing" in res.answer_text


def test_numbers_only_from_user_text():
    res = run("post a request for 100 office chairs")
    r = rows(res)
    assert r["quantity"].value == "100" and r["target_price"].value is None
    assert not any(ch.isdigit() for ch in res.answer_text)


def test_no_downstream_calls():
    clients = build_mock_clients()

    def boom(*a, **k):
        raise AssertionError("downstream call")

    for name in ("sourcing", "logistics", "trust", "tracking"):
        svc = getattr(clients, name, None)
        for m in ("search", "landed_cost", "supplier_score", "validate"):
            if svc is not None and hasattr(svc, m):
                setattr(svc, m, boom)
    res = asyncio.run(Assistant(clients, Settings(clients="mock")).handle("انشر طلب شراء 10 طن حديد الى البصرة"))
    assert res.intent.value == "create_rfq_draft" and res.warnings == []


def test_message_still_blocked():
    res = run("send a message to the supplier about my request for 100 chairs")
    assert res.intent.value == "help" and "private_message_blocked" in res.warnings
