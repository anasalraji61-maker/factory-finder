"""Price history: bucketing, statistics, trend and deterministic seeded mock history (pure, no I/O)."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel

from .models import Money

Bucket = Literal["day", "week", "month"]
FLAT_BAND_PCT = Decimal("1")  # |change| <= 1% is "flat"
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Obs:
    t: datetime
    price: Decimal
    currency: str


class PricePoint(BaseModel):
    t: datetime  # bucket start (UTC)
    avg: Decimal
    min: Decimal
    max: Decimal
    n: int


class PriceSummary(BaseModel):
    min: Decimal
    max: Decimal
    avg: Decimal
    current: Decimal
    first: Decimal
    observations: int


class PriceTrend(BaseModel):
    direction: Literal["up", "down", "flat"]
    change_pct: Decimal | None = None
    insufficient_data: bool = False


class PriceHints(BaseModel):
    """Additive hints for watchlist/alert evaluation (e.g. a sensible target price)."""

    at_period_low: bool
    at_period_high: bool
    current_vs_min_pct: Decimal  # how far the current price is above the period low
    suggested_target: Money  # the period low: alert when the price falls back to it


class PriceHistory(BaseModel):
    listing_id: str
    currency: str
    unit: str | None = None
    days: int
    bucket: Bucket
    synthetic: bool = False  # True: deterministic mock history (mock catalog listings)
    points: list[PricePoint] = []
    summary: PriceSummary | None = None
    trend: PriceTrend
    hints: PriceHints | None = None


def should_record(last: Obs | None, price: Decimal, currency: str, now: datetime, window_hours: float) -> bool:
    """Skip an observation identical (price + currency) to the latest one made within the window."""
    if last is None:
        return True
    return not (last.price == price and last.currency == currency and now - last.t < timedelta(hours=window_hours))


def _bucket_start(t: datetime, bucket: Bucket) -> datetime:
    d = t.astimezone(UTC).date()
    if bucket == "week":
        d = d - timedelta(days=d.weekday())
    elif bucket == "month":
        d = d.replace(day=1)
    return datetime.combine(d, time.min, tzinfo=UTC)


def _q(x: Decimal) -> Decimal:
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


def build(
    listing_id: str,
    obs: list[Obs],
    days: int,
    bucket: Bucket,
    now: datetime,
    unit: str | None = None,
    synthetic: bool = False,
    currency: str | None = None,
) -> PriceHistory:
    """Series for the last ``days`` days. Only observations in the newest currency are used."""
    since = now - timedelta(days=days)
    rows = sorted((o for o in obs if o.t >= since), key=lambda o: o.t)
    if rows:
        currency = rows[-1].currency
        rows = [o for o in rows if o.currency == currency]
    cur = currency or ""
    groups: dict[datetime, list[Decimal]] = {}
    for o in rows:
        groups.setdefault(_bucket_start(o.t, bucket), []).append(o.price)
    points = [
        PricePoint(t=t, avg=_q(sum(v, Decimal(0)) / len(v)), min=min(v), max=max(v), n=len(v))
        for t, v in sorted(groups.items())
    ]
    base = dict(listing_id=listing_id, currency=cur, unit=unit, days=days, bucket=bucket, synthetic=synthetic)
    if not rows:
        return PriceHistory(**base, points=[], trend=PriceTrend(direction="flat", insufficient_data=True))
    prices = [o.price for o in rows]
    first, current = prices[0], prices[-1]
    summary = PriceSummary(
        min=min(prices), max=max(prices), avg=_q(sum(prices, Decimal(0)) / len(prices)),
        current=current, first=first, observations=len(prices),
    )
    if len(rows) < 2 or len(points) < 2 or first <= 0:
        return PriceHistory(
            **base, points=points, summary=summary,
            trend=PriceTrend(direction="flat", insufficient_data=True),
        )
    pct = _q((current - first) / first * 100)
    direction = "up" if pct > FLAT_BAND_PCT else "down" if pct < -FLAT_BAND_PCT else "flat"
    lo = summary.min
    hints = PriceHints(
        at_period_low=current == lo,
        at_period_high=current == summary.max,
        current_vs_min_pct=_q((current - lo) / lo * 100) if lo > 0 else Decimal(0),
        suggested_target=Money(amount=lo, currency=cur),
    )
    return PriceHistory(
        **base, points=points, summary=summary, hints=hints,
        trend=PriceTrend(direction=direction, change_pct=pct),
    )


def _unit(listing_id: str, tag: str) -> float:
    """Deterministic value in [-1, 1] from (id, tag)."""
    h = hashlib.sha256(f"{listing_id}|{tag}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**31 - 1


def synthetic_observations(listing_id: str, current: Decimal, currency: str, now: datetime, days: int) -> list[Obs]:
    """One observation per day, ending at ``current`` today. Same id + same day => identical series."""
    days = max(1, min(days, 365))
    slope = _unit(listing_id, "slope") * 0.0004  # fractional drift per day (-0.04% .. +0.04%)
    phase = (_unit(listing_id, "phase") + 1) * math.pi
    today = now.astimezone(UTC).date()

    def raw(d: int) -> float:
        day = today - timedelta(days=d)
        wave = 0.05 * math.sin(day.toordinal() / 21.0 + phase)
        noise = 0.012 * _unit(listing_id, f"n{day.toordinal()}")
        return (1 - slope * d) * (1 + wave + noise)

    r0 = raw(0)
    out: list[Obs] = []
    for d in range(days, -1, -1):
        price = _q(current * Decimal(repr(raw(d) / r0))) if d else current
        if price <= 0:
            price = current
        t = now if d == 0 else datetime.combine(today - timedelta(days=d), time(12), tzinfo=UTC)
        out.append(Obs(t=t, price=price, currency=currency))
    return out


def day_floor(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)
