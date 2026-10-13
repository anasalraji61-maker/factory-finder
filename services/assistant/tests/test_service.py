import pytest

from ff_assistant.clients.mock import (
    MockLogisticsClient,
    MockSourcingClient,
    MockTrackingClient,
    MockTrustClient,
)
from ff_assistant.config import Settings
from ff_assistant.domain.models import Location
from ff_assistant.service import Assistant


async def test_search_orchestrates_all_three(assistant, clients):
    r = await assistant.handle("أريد خط إنتاج معجنات مستعمل من الصين يوصل بغداد")
    assert r.intent.value == "search"
    assert r.listings and r.listings[0].kind.value == "production_line"
    assert r.quote and r.trust and r.trust.supplier_id == "sup_cn_001"
    assert "بغداد" in r.answer_text and "ثقة" in r.answer_text
    assert clients.sourcing.calls[0]["origin_country"] == "CN"


async def test_quote_weight_from_tons(assistant, clients):
    r = await assistant.handle("شكد كلفة شحن 2 طن حبيبات بلاستيك من ننغبو الى البصرة")
    assert r.intent.value == "quote" and r.quote is not None
    goods = clients.logistics.calls[0]["goods"]
    assert goods["total_weight_kg"] == "2000.00"
    assert clients.logistics.calls[0]["destination"] == {"country_code": "IQ", "city": "Basra"}
    assert "البصرة" in r.answer_text


async def test_budget_filter_passed_to_sourcing(assistant, clients):
    r = await assistant.handle("منو عنده ألواح طاقة شمسية بسعر أقل من 100 دولار")
    assert clients.sourcing.calls[0]["max_price"] == "100"
    assert r.listings and r.quote is None and "مدينة الوصول" in r.answer_text


async def test_trust_and_track(assistant):
    r = await assistant.handle("هل المورد sup_cn_001 موثوق؟")
    assert r.trust.score == 82 and "82" in r.answer_text
    ok = await assistant.handle("تتبع الحاوية CSQU3054383")
    assert "صحيح" in ok.answer_text
    bad = await assistant.handle("تتبع الحاوية CSQU3054384")
    assert "غير صحيح" in bad.answer_text


async def test_english_query_and_help(assistant):
    r = await assistant.handle("I need a used CNC machine from Germany delivered to Erbil")
    assert r.listings[0].supplier.location.country_code == "DE" and r.quote
    h = await assistant.handle("مرحبا")
    assert h.intent.value == "help" and "مُوَرِّد" in h.answer_text


async def test_request_destination_fallback(assistant):
    r = await assistant.handle("كراسي بلاستك من الصين", Location(country_code="IQ", city="Basra"))
    assert r.quote is not None


@pytest.mark.parametrize(
    ("failing", "text", "warning"),
    [
        ("sourcing", "ابي كراسي بلاستك من الصين الى اربيل", "sourcing_unavailable"),
        ("logistics", "ابي كراسي بلاستك من الصين الى اربيل", "logistics_unavailable"),
        ("trust", "هل المورد sup_cn_001 موثوق؟", "trust_unavailable"),
        ("tracking", "تتبع الحاوية CSQU3054383", "tracking_unavailable"),
    ],
)
async def test_degradation(failing, text, warning):
    from ff_assistant.clients.base import Clients

    mocks = dict(sourcing=MockSourcingClient(), logistics=MockLogisticsClient(), trust=MockTrustClient(), tracking=MockTrackingClient())
    mocks[failing].fail = True
    r = await Assistant(Clients(**mocks), Settings(clients="mock")).handle(text)
    assert warning in r.warnings and r.answer_text
    if failing == "logistics":
        assert r.listings and r.quote is None
    if failing == "trust":
        assert r.trust is None


async def test_trust_failure_falls_back_to_listing_score():
    from ff_assistant.clients.base import Clients

    c = Clients(sourcing=MockSourcingClient(), logistics=MockLogisticsClient(), trust=MockTrustClient(fail=True), tracking=MockTrackingClient())
    r = await Assistant(c, Settings(clients="mock")).handle("ابي كراسي بلاستك من الصين")
    assert r.trust.score == 64 and "trust_unavailable" in r.warnings
