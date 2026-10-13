from decimal import Decimal

import pytest

from ff_assistant.domain.parser import parse

CASES = [
    ("أريد خط إنتاج معجنات مستعمل من الصين يوصل بغداد",
     dict(intent="search", kind="production_line", condition="used", origin=("CN", None), destination=("IQ", "Baghdad"))),
    ("ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل",
     dict(intent="search", quantity=Decimal(500), unit="piece", origin=("CN", None), destination=("IQ", "Erbil"), kw="plastic chair")),
    ("شكد كلفة شحن 2 طن حبيبات بلاستيك من ننغبو الى البصرة",
     dict(intent="quote", quantity=Decimal(2), unit="ton", kind="raw_material", origin=("CN", "Ningbo"), destination=("IQ", "Basra"))),
    ("منو عنده ألواح طاقة شمسية بسعر أقل من 100 دولار",
     dict(intent="search", budget=(Decimal(100), "USD", "max"), kw="solar panel")),
    ("هل المورد sup_cn_001 موثوق؟", dict(intent="trust", supplier_id="sup_cn_001")),
    ("تتبع الحاوية CSQU3054383", dict(intent="track", reference="CSQU3054383", reference_type="container")),
    ("I need a used CNC machine from Germany delivered to Erbil",
     dict(intent="search", condition="used", origin=("DE", None), destination=("IQ", "Erbil"), kw="CNC machine")),
    ("مرحبا", dict(intent="help")),
    ("Track AWB 176-12345675", dict(intent="track", reference_type="awb")),
]


@pytest.mark.parametrize(("text", "exp"), CASES)
def test_parse(text, exp):
    p = parse(text)
    assert p.intent.value == exp["intent"]
    for key in ("kind", "condition"):
        if key in exp:
            assert getattr(p, key).value == exp[key]
    for key in ("quantity", "unit", "supplier_id", "reference", "reference_type"):
        if key in exp:
            assert getattr(p, key) == exp[key]
    if "origin" in exp:
        assert (p.origin.country_code, p.origin.city) == exp["origin"]
    if "destination" in exp:
        assert (p.destination.country_code, p.destination.city) == exp["destination"]
    if "budget" in exp:
        b = p.budget
        assert (b.amount, b.currency, b.bound) == exp["budget"]
    if "kw" in exp:
        assert exp["kw"] in p.keywords


def test_arabic_indic_digits_and_budget_currency():
    p = parse("ابي ٢٠٠ جهاز بسعر اكثر من ٥٠ يورو")
    assert p.quantity == Decimal(200)
    assert (p.budget.amount, p.budget.currency, p.budget.bound) == (Decimal(50), "EUR", "min")


def test_default_destination_used_when_missing():
    from ff_assistant.domain.models import Location

    p = parse("كراسي بلاستك من الصين", default_destination=Location(country_code="IQ", city="Basra"))
    assert p.destination.city == "Basra"
