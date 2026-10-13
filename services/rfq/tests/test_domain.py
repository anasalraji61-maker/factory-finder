from decimal import Decimal

import pytest

from ff_rfq.domain.commission import compute_commission
from ff_rfq.domain.enums import ListingKind as K
from ff_rfq.domain.enums import OfferStatus as O
from ff_rfq.domain.enums import RequestStatus as R
from ff_rfq.domain.errors import InvalidTransition, UnsupportedCurrency
from ff_rfq.domain.state import offer_transition, request_transition


@pytest.mark.parametrize(("kind", "rate"), [(K.PRODUCT, "0.03"), (K.RAW_MATERIAL, "0.02"), (K.PRODUCTION_LINE, "0.04")])
def test_rates_by_kind(kind, rate):
    c = compute_commission(Decimal("10000.00"), "USD", kind)
    assert c.rate == Decimal(rate) and c.amount == Decimal("10000") * Decimal(rate) and not c.min_fee_applied


def test_min_fee_usd_and_other_currency():
    c = compute_commission(Decimal("100.00"), "USD", K.PRODUCT)
    assert c.amount == Decimal("25.00") and c.min_fee_applied
    cny = compute_commission(Decimal("100.00"), "CNY", K.PRODUCT)  # 25 USD / 0.14 = 178.5714... -> 178.58
    assert cny.amount == Decimal("178.58") and cny.min_fee_applied


def test_rounding_and_unsupported_currency():
    assert compute_commission(Decimal("1234.55"), "USD", K.PRODUCT).amount == Decimal("37.04")
    with pytest.raises(UnsupportedCurrency):
        compute_commission(Decimal("1"), "XXX", K.PRODUCT)


def test_request_machine():
    assert request_transition(R.OPEN, "receive_offer") is R.NEGOTIATING
    assert request_transition(R.NEGOTIATING, "award") is R.AWARDED
    for status in (R.AWARDED, R.CLOSED, R.EXPIRED):
        with pytest.raises(InvalidTransition) as e:
            request_transition(status, "close")
        assert e.value.code == "invalid_request_transition" and e.value.details["allowed_actions"] == []
    with pytest.raises(InvalidTransition):
        request_transition(R.OPEN, "release")


def test_offer_machine():
    assert offer_transition(O.ACTIVE, "accept") is O.ACCEPTED
    for status in (O.ACCEPTED, O.WITHDRAWN, O.REJECTED, O.EXPIRED):
        for action in ("accept", "withdraw", "reject"):
            with pytest.raises(InvalidTransition):
                offer_transition(status, action)
