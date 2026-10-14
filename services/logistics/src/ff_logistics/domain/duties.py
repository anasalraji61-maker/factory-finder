import json
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources

from .money import D


def load_json(name: str) -> dict:
    return json.loads(resources.files("ff_logistics.data").joinpath(name).read_text("utf-8"))


@dataclass(frozen=True)
class DutyEstimate:
    duty_rate_pct: Decimal
    vat_pct: Decimal
    clearance_fee_usd: Decimal
    rule: str
    duty_range_pct: tuple[Decimal, Decimal] | None = None
    vat_range_pct: tuple[Decimal, Decimal] | None = None
    as_of: str | None = None
    confidence: str | None = None


def hs_chapter(hs_code: str | None, category: str | None, table: dict) -> str | None:
    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())
    if len(digits) >= 2:
        return digits[:2]
    if category:
        return table["category_chapters"].get(category.strip().lower().replace(" ", "_"))
    return None


def duty_rule(table: dict, country: str, hs_code: str | None, category: str | None,
              origin_country: str | None = None) -> DutyEstimate:
    c = table["countries"].get(country)
    if c is None:
        return DutyEstimate(D(10), D(0), D(150), f"{country}: no table; generic 10% duty, no VAT")
    chap = hs_chapter(hs_code, category, table)
    rate = D(c["chapters"].get(chap, c["default_duty_pct"])) if chap else D(c["default_duty_pct"])
    rule = f"{country} chapter {chap}: {rate}%" if chap in c["chapters"] else \
        f"{country} default duty {rate}%"
    extra = D(c.get("origin_additional_pct", {}).get(origin_country or "", 0))
    if extra:
        rate += extra
        rule += f" + {extra}% additional duty on {origin_country}-origin goods"
    dr, vr = c.get("duty_range_pct"), c.get("vat_range_pct")
    return DutyEstimate(
        rate, D(c["vat_pct"]), D(c["clearance_fee_usd"]), rule,
        (D(dr[0]) + extra, D(dr[1]) + extra) if dr else None, (D(vr[0]), D(vr[1])) if vr else None,
        c.get("as_of"), c.get("confidence"))


def de_minimis(table: dict, country: str) -> dict | None:
    """De minimis record for a destination (threshold/currency/applies_to/status/confidence) or None."""
    dm = table["countries"].get(country, {}).get("de_minimis")
    return dm if dm and dm.get("threshold") else None
