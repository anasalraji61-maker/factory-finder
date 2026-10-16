"""Security review 2026-10 l: money amounts are length-bounded."""
import pytest

from ff_notifications.domain.money import Money, MoneyError, parse_amount


@pytest.mark.parametrize("v", ["9" * 5000, "1." + "0" * 5000, "1" * 19])
def test_parse_amount_rejects_oversized(v):
    with pytest.raises(MoneyError):
        parse_amount(v)


def test_normal_amounts_still_parse():
    assert str(Money.of("1234.50", "USD").amount) == "1234.50"
