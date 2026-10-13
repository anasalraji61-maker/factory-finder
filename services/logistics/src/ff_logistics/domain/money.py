from decimal import ROUND_HALF_UP, Decimal

ZERO_DECIMAL = {"IQD", "IRR", "JPY", "KRW", "VND"}


def D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def quantize(amount: Decimal, currency: str) -> Decimal:
    exp = Decimal(1) if currency in ZERO_DECIMAL else Decimal("0.01")
    return D(amount).quantize(exp, rounding=ROUND_HALF_UP)


def money(amount: Decimal, currency: str) -> dict:
    return {"amount": str(quantize(amount, currency)), "currency": currency}
