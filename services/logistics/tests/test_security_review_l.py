"""Security review 2026-10 l: unbounded Decimals on the public quote / convert endpoints."""
import pytest

from ff_logistics.testing import req


@pytest.mark.parametrize("field,val", [
    ("kg", "1e999999"), ("kg", "9" * 40), ("value", "1e999999"), ("value", "9" * 40), ("m3", "1e100000"),
    ("kg", "1e-999999"), ("kg", "NaN"), ("kg", "Infinity"),
])
def test_quote_rejects_absurd_numbers(client, field, val):
    body = req(**{field: val}) if field != "kg" and field != "m3" and field != "value" else req(**{field: val})
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 422, (field, val, r.status_code, r.text[:200])


@pytest.mark.parametrize("amount", ["1e999999", "9" * 40, "NaN", "-1e999999"])
def test_convert_rejects_absurd_amount(client, amount):
    r = client.post("/v1/fx/convert", json={"amount": amount, "from": "USD", "to": "EUR"})
    assert r.status_code == 422, (amount, r.status_code, r.text[:200])


def test_quantity_bounded(client):
    body = req()
    body["goods"]["quantity"] = "1e999999"
    r = client.post("/v1/quotes/landed-cost", json=body)
    assert r.status_code == 422, r.text[:200]
