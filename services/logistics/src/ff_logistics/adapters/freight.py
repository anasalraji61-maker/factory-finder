"""Freight rate providers (CLAUDE.md rules 4, 5, 6, 8).

`FreightRateProvider.quote()` returns a `FreightQuote` for the main leg of one route, or None
meaning "no live rate, use the built-in tables" (what `MockFreight` always does, i.e. the
pre-existing deterministic behaviour). `HttpFreightProvider` is a Freightos-style estimator
client, OFF by default and UNVERIFIED against the live API: endpoint, params and response shape
below are best-known assumptions; replace the recorded fixture with a real response before use.

Guarantees: >= 3 s between requests per host, TTL cache, honest User-Agent, key from config/env
only (never printed), kill-switch, cooldown after failures, and any error raises
`FreightUnavailable` so the engine falls back to the tables. Quotes are always estimates.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

MIN_INTERVAL_FLOOR_S = 3.0
GLOBAL_KILL_SWITCH_ENV = "FF_LOGISTICS_KILL_SWITCH"
_TRUTHY = {"1", "true", "yes", "on"}
# engine mode -> estimator load type (UNVERIFIED names). Rail has no equivalent: tables are used.
LOAD_TYPES = {
    "sea_fcl_20": "container20", "sea_fcl_40": "container40", "sea_fcl_40hc": "container40hc",
    "sea_lcl": "boxes", "air": "boxes",
}


class FreightUnavailable(RuntimeError):
    """Live provider cannot answer (disabled, unconfigured, 4xx/5xx, timeout, bad payload)."""


@dataclass(frozen=True)
class FreightRequest:
    mode: str
    origin_id: str
    origin_name: str
    origin_country: str
    dest_id: str
    dest_name: str
    dest_country: str
    weight_kg: Decimal
    volume_m3: Decimal
    containers: int | None = None


@dataclass(frozen=True)
class FreightQuote:
    low: Decimal
    high: Decimal  # low <= high; the engine uses the midpoint and the half-range as spread
    currency: str
    source: str
    fetched_at: str
    estimate: bool = True
    days: tuple[int, int] | None = None


class FreightRateProvider(Protocol):
    async def quote(self, req: FreightRequest) -> FreightQuote | None: ...


class MockFreight:
    """No live rates: the engine keeps using its built-in tables (existing behaviour)."""

    async def quote(self, req: FreightRequest) -> FreightQuote | None:
        return None


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class HttpFreightProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        user_agent: str = "FactoryFinderBot/0.1 (+https://github.com/factory-finder; logistics)",
        min_interval_s: float = MIN_INTERVAL_FLOOR_S,
        cache_ttl_s: float = 6 * 3600,
        cooldown_s: float = 60.0,
        timeout_s: float = 5.0,
        kill_switch_env: str = "FF_LOGISTICS_FREIGHT_DISABLED",
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now_iso: Callable[[], str] = utcnow_iso,
    ):
        self.base_url, self._key, self.user_agent = base_url.rstrip("/"), api_key, user_agent
        self.min_interval_s = max(min_interval_s, MIN_INTERVAL_FLOOR_S)
        self.cache_ttl_s, self.cooldown_s, self.timeout_s = cache_ttl_s, cooldown_s, timeout_s
        self._kill_env, self._env = kill_switch_env, env if env is not None else os.environ
        self._client, self._clock, self._sleep, self._now = client, clock, sleep, now_iso
        self._cache: dict[tuple, tuple[float, FreightQuote]] = {}
        self._next_at = 0.0
        self._cooldown_until = 0.0
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:  # never expose the key
        return f"<HttpFreightProvider {self.base_url} configured={bool(self._key)}>"

    def killed(self) -> bool:
        return any(
            n and self._env.get(n, "").strip().lower() in _TRUTHY
            for n in (GLOBAL_KILL_SWITCH_ENV, self._kill_env)
        )

    @staticmethod
    def _params(req: FreightRequest) -> dict[str, str]:
        p = {
            "loadtype": LOAD_TYPES[req.mode],
            "origin": req.origin_id, "destination": req.dest_id,  # UNVERIFIED: may need UN/LOCODE
            "weight": f"{req.weight_kg:.0f}", "volume": f"{req.volume_m3:.2f}",
        }
        if req.containers:
            p["quantity"] = str(req.containers)
        return p

    async def quote(self, req: FreightRequest) -> FreightQuote | None:
        if req.mode not in LOAD_TYPES:
            return None  # unsupported mode: not an error, tables apply
        if self.killed():
            raise FreightUnavailable("freight provider kill-switch is on")
        if not self._key:
            raise FreightUnavailable("freight provider not configured")
        params = self._params(req)
        key = tuple(sorted(params.items()))
        async with self._lock:
            now = self._clock()
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
            if now < self._cooldown_until:
                raise FreightUnavailable("freight provider cooling down after errors")
            if self._next_at > now:
                await self._sleep(self._next_at - now)
                now = self._next_at
            self._next_at = now + self.min_interval_s
            try:
                q = await self._fetch(params)
            except FreightUnavailable:
                self._cooldown_until = self._clock() + self.cooldown_s
                raise
            self._cache[key] = (self._clock() + self.cache_ttl_s, q)
            return q

    async def _fetch(self, params: dict[str, str]) -> FreightQuote:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            r = await client.get(
                f"{self.base_url}/shippingCalculator", params=params,
                headers={"User-Agent": self.user_agent, "x-apikey": self._key,
                         "Accept": "application/json"},
            )
            if r.status_code in (401, 403, 429):
                raise FreightUnavailable(f"freight provider HTTP {r.status_code}; not retrying")
            r.raise_for_status()
            return self.parse(r.json())
        except FreightUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as exc:  # timeouts, 5xx, bad JSON
            raise FreightUnavailable(f"freight provider error: {type(exc).__name__}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    def parse(self, payload: dict) -> FreightQuote:
        """UNVERIFIED shape: response.estimatedFreightRates.{min,max}.{price.moneyAmount,transitTime}."""
        try:
            rates = payload["response"]["estimatedFreightRates"]
            lo_m = rates["min"]["price"]["moneyAmount"]
            hi_m = rates["max"]["price"]["moneyAmount"]
            cur = str(lo_m["currencyCode"]).upper()
            if str(hi_m["currencyCode"]).upper() != cur:
                raise ValueError("mixed currencies")
            lo, hi = Decimal(str(lo_m["amount"])), Decimal(str(hi_m["amount"]))
            if hi < lo:
                lo, hi = hi, lo
            if lo <= 0:
                raise ValueError("non-positive rate")
            days = None
            try:
                days = (int(rates["min"]["transitTime"]["min"]), int(rates["max"]["transitTime"]["max"]))
                if days[0] > days[1] or days[0] < 0:
                    days = None
            except (KeyError, TypeError, ValueError):
                pass
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise FreightUnavailable("freight provider returned an unusable payload") from exc
        return FreightQuote(lo, hi, cur, "freight rate API (Freightos-style, UNVERIFIED)",
                            self._now(), True, days)
