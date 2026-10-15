from decimal import Decimal

import pytest

from ff_payments.domain import ledger, state
from ff_payments.domain.commission import compute_commission
from ff_payments.domain.enums import Direction, InvoiceStatus, ListingKind
from ff_payments.domain.errors import InvalidTransition
from ff_payments.service import normalize_amount

S = InvoiceStatus


@pytest.mark.parametrize(("kind", "subtotal", "fee", "min_applied"), [
    (ListingKind.PRODUCT, "12500.00", "375.00", False),
    (ListingKind.RAW_MATERIAL, "12500.00", "250.00", False),
    (ListingKind.PRODUCTION_LINE, "12500.00", "500.00", False),
    (ListingKind.PRODUCT, "100.00", "25.00", True),
    (ListingKind.PRODUCT, "333.33", "25.00", True),
    (ListingKind.PRODUCT, "1000.50", "30.02", False),  # 30.015 -> half-up
])
def test_commission_rule(kind, subtotal, fee, min_applied):
    c = compute_commission(Decimal(subtotal), "USD", kind)
    assert (str(c.amount), c.min_fee_applied) == (fee, min_applied)
    assert isinstance(c.amount, Decimal)


def test_commission_min_fee_in_other_currency_and_unsupported():
    assert compute_commission(Decimal("1"), "EUR", ListingKind.PRODUCT).amount == Decimal("23.15")
    with pytest.raises(Exception, match="not supported"):
        compute_commission(Decimal("1"), "XXX", ListingKind.PRODUCT)


def test_status_machine_complete():
    allowed = {(a, b) for a, bs in state.TRANSITIONS.items() for b in bs}
    for a in S:
        for b in S:
            assert state.can(a, b) == ((a, b) in allowed)
    for terminal in (S.EXPIRED, S.FAILED, S.REFUNDED):
        assert state.TRANSITIONS[terminal] == frozenset()
    assert state.can(S.PAID, S.REFUNDED) and not state.can(S.PAID, S.FAILED)
    with pytest.raises(InvalidTransition):
        state.require(S.EXPIRED, S.PAID)


def test_ledger_balance_checks():
    legs = ledger.payment_legs(provider="mock", payee="platform", kind="commission",
                               amount=Decimal("0.10"), currency="USD")
    ledger.check_balanced(legs)
    ledger.check_balanced(legs + ledger.refund_legs(legs))
    with pytest.raises(ledger.LedgerImbalance):
        ledger.check_balanced([ledger.Leg("a", Direction.DEBIT, Decimal("1"), "USD")])
    with pytest.raises(ledger.LedgerImbalance):  # balanced only if currencies are mixed: not allowed
        ledger.check_balanced([ledger.Leg("a", Direction.DEBIT, Decimal("1"), "USD"),
                               ledger.Leg("b", Direction.CREDIT, Decimal("1"), "EUR")])
    with pytest.raises(ledger.LedgerImbalance):
        ledger.check_balanced([])


def test_decimal_exactness_no_float_drift():
    total = sum((Decimal("0.1") for _ in range(10)), Decimal(0))
    assert total == Decimal("1.0")
    assert normalize_amount(Decimal("0.10"), "USD") == "0.10"
    assert normalize_amount(Decimal("1"), "USD") == "1.00"
    assert normalize_amount(Decimal("1.000001"), "USDT") == "1.000001"
    with pytest.raises(Exception, match="decimals"):
        normalize_amount(Decimal("1.005"), "USD")


def test_commission_boundaries_and_precision():
    # exactly at the floor: 25 / 3% = 833.333..; 833.34 -> 25.0002 -> 25.00, not min-fee
    assert compute_commission(Decimal("833.34"), "USD", ListingKind.PRODUCT).min_fee_applied is False
    assert compute_commission(Decimal("833.00"), "USD", ListingKind.PRODUCT).min_fee_applied is True
    # 6-decimal subtotal is rounded half-up once, to cents
    assert compute_commission(Decimal("1000.166667"), "USD", ListingKind.PRODUCT).amount == Decimal("30.01")
    big = compute_commission(Decimal("999999999999"), "USD", ListingKind.PRODUCTION_LINE)
    assert big.amount == Decimal("39999999999.96")
    # floor in a weak currency rounds up (never under-charges the 25 USD minimum)
    iqd = compute_commission(Decimal("1"), "IQD", ListingKind.PRODUCT)
    assert iqd.amount * Decimal("0.00076") >= Decimal("25")
