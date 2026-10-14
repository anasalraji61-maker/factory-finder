"""Low/base/high sensitivity of a landed-cost total to freight-rate and FX moves (Decimal-exact)."""
from decimal import Decimal

from .duties import load_json
from .money import D, money, quantize

_VOL = load_json("fx_volatility.json")
SENSITIVITY_NOTE = ("Sensitivity is a stress range, not a forecast: freight uses the same main-leg spread as the "
                    "estimate range; FX uses indicative per-currency volatility buckets (data/fx_volatility.json).")


def currency_vol_pct(cur: str) -> Decimal:
    return D(_VOL["pct"].get(cur, _VOL["default_pct"]))


def pair_vol_pct(a: str, b: str) -> Decimal:
    """Stress move of a vs b: zero for the same currency, else the larger of the two vs-USD buckets."""
    return Decimal(0) if a == b else max(currency_vol_pct(a), currency_vol_pct(b))


def _band(base: Decimal, delta: Decimal, cur: str, shock_pct: Decimal) -> dict:
    return {"low": money(max(base - delta, Decimal(0)), cur), "base": money(base, cur),
            "high": money(base + delta, cur), "shock_pct": format(shock_pct.normalize(), "f")}


def sensitivity(total: Decimal, freight_amount: Decimal, freight_spread: Decimal, goods_amount: Decimal,
                goods_currency: str, disp: str) -> dict:
    """total/freight_amount/goods_amount are already in `disp`. Goods are exposed to goods-currency vs disp
    moves; every other line is USD-denominated and exposed to USD vs disp."""
    f_delta = quantize(freight_amount * freight_spread, disp)
    g_pct, o_pct = pair_vol_pct(goods_currency, disp), pair_vol_pct("USD", disp)
    other = total - goods_amount
    fx_delta = quantize(goods_amount * g_pct / 100 + other * o_pct / 100, disp)
    eff = (fx_delta / total * 100) if total > 0 else Decimal(0)
    return {
        "currency": disp,
        "freight": _band(total, f_delta, disp, (freight_spread * 100)),
        "fx": {**_band(total, fx_delta, disp, eff.quantize(Decimal("0.01"))),
               "goods_currency": goods_currency},
        "combined": {k: v for k, v in _band(total, f_delta + fx_delta, disp, Decimal(0)).items()
                     if k != "shock_pct"},
        "estimate": True,
        "note": SENSITIVITY_NOTE,
    }
