"""FX providers: Protocol, deterministic mock, optional ECB-based public API with cache + fallback."""
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx

from ..errors import ApiError

MOCK_USD_RATES = {  # units of currency per 1 USD (static, approximate)
    "USD": "1", "EUR": "0.92", "GBP": "0.79", "CNY": "7.20", "IQD": "1310", "TRY": "34.5",
    "AED": "3.6725", "SAR": "3.75", "KWD": "0.307", "JOD": "0.709", "EGP": "48.5", "INR": "83.5",
    "RUB": "92", "IRR": "42000", "JPY": "150", "KRW": "1350", "CAD": "1.36",
    "AUD": "1.52", "CHF": "0.88", "SGD": "1.34", "MYR": "4.7", "ZAR": "18.5", "PHP": "56", "SEK": "10.5",
    "PLN": "4.0", "MXN": "17.5", "BRL": "5.0", "HKD": "7.8", "TWD": "32", "CZK": "23", "HUF": "360",
}
MOCK_TS = "2026-01-01T00:00:00Z"


@dataclass(frozen=True)
class FxRates:
    base: str
    rates: dict[str, Decimal]  # per 1 unit of base
    timestamp: str
    source: str


class FxProvider(Protocol):
    async def usd_rates(self) -> FxRates: ...


class MockFx:
    async def usd_rates(self) -> FxRates:
        return FxRates("USD", {k: Decimal(v) for k, v in MOCK_USD_RATES.items()}, MOCK_TS, "mock")


class EcbFx:
    """Frankfurter (ECB reference rates, no key). Cached; falls back to mock; fills gaps (IQD, IRR…)."""

    def __init__(self, url: str, ttl: int = 21600, client: httpx.AsyncClient | None = None):
        self.url, self.ttl, self._client = url, ttl, client
        self._cache: tuple[float, FxRates] | None = None
        self._mock = MockFx()

    async def usd_rates(self) -> FxRates:
        if self._cache and time.monotonic() - self._cache[0] < self.ttl:
            return self._cache[1]
        fallback = await self._mock.usd_rates()
        try:
            client = self._client or httpx.AsyncClient(timeout=5)
            try:
                r = await client.get(self.url, params={"base": "USD"})
                r.raise_for_status()
                data = r.json()
            finally:
                if self._client is None:
                    await client.aclose()
            rates = dict(fallback.rates)
            rates.update({k: Decimal(str(v)) for k, v in data["rates"].items()})
            rates["USD"] = Decimal(1)
            res = FxRates("USD", rates, f"{data.get('date', '')}T00:00:00Z", "ecb")
            self._cache = (time.monotonic(), res)
            return res
        except Exception:
            return FxRates("USD", fallback.rates, fallback.timestamp, "mock-fallback")


class FxService:
    def __init__(self, provider: FxProvider):
        self.provider = provider

    async def table(self, base: str = "USD") -> FxRates:
        usd = await self.provider.usd_rates()
        if base not in usd.rates:
            raise ApiError("unknown_currency", f"Unsupported currency {base}", 400)
        b = usd.rates[base]
        return FxRates(base, {k: v / b for k, v in usd.rates.items()}, usd.timestamp, usd.source)

    async def rate(self, frm: str, to: str) -> tuple[Decimal, FxRates]:
        t = await self.table(frm)
        if to not in t.rates:
            raise ApiError("unknown_currency", f"Unsupported currency {to}", 400)
        return t.rates[to], t


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
