"""Generic adapter for a LICENSED / OFFICIAL supplier-data HTTP API (CLAUDE.md rules 4, 5, 6, 8).

Everything provider-specific lives in a `ProviderConfig` (base URL, auth env var names, field
mapping table), so a new licensed feed is configuration plus, at most, a tiny subclass.

Compliance built in:
  * official/licensed API only (no page scraping, no robots bypass needed; `tos_note` documents terms)
  * >= 3 s between requests per host (config value is clamped to this floor), response cache
  * honest User-Agent; credentials read from the environment at call time, never stored/printed
  * kill-switch: global `FF_SOURCING_KILL_SWITCH` or the provider's own env var
  * 401/403/429 raise SourceBlocked, nothing retries or bypasses; callers degrade to mock
Money is parsed with Decimal; every listing carries its currency.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from ..domain.cache import TTLCache
from ..domain.models import ListingDetail, SearchQuery, Supplier
from ._norm import build_listing, dec
from .base import Health, SourceAdapter
from .http_base import HostRateLimiter, SourceBlocked, SourceNotConfigured

log = logging.getLogger(__name__)

GLOBAL_KILL_SWITCH_ENV = "FF_SOURCING_KILL_SWITCH"
MIN_INTERVAL_FLOOR_S = 3.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # provider responses above this are refused
_TRUTHY = {"1", "true", "yes", "on"}
_PRICE_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


class ProviderDisabled(RuntimeError):
    """Kill-switch is on."""


class ProviderConfig(BaseModel):
    id: str
    name: str
    base_url: str
    search_path: str = "/search"
    method: str = "GET"
    query_param: str = "q"
    limit_param: str = "limit"
    extra_params: dict[str, str] = {}
    api_key_env: str = ""  # NAME of the env var holding the key (never the key itself)
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    kill_switch_env: str = ""  # per-provider kill switch env var name
    results_path: str = "results"  # dotted path to the item list in the response
    # target field -> dotted source path. Targets: id, title, price_min, price_max, price_range,
    # currency, supplier_id, supplier_name, country, city, url, images, moq, unit, verified
    field_map: dict[str, str] = {}
    currency_default: str = "USD"
    country_default: str = "CN"
    mode: str = "licensed_feed"
    min_interval_s: float = Field(default=MIN_INTERVAL_FLOOR_S)
    cache_ttl_s: float = 300.0
    timeout_s: float = 8.0
    user_agent: str = "FactoryFinderBot/0.1 (+https://github.com/factory-finder; sourcing)"
    tos_note: str = ""


def get_path(obj: Any, path: str) -> Any:
    """Dotted lookup; `[]` fans out over a list (`images[].url`); `[n]` indexes. Missing -> None."""
    cur: list[Any] = [obj]
    fan = False
    for part in path.split("."):
        name, _, rest = part.partition("[")
        nxt: list[Any] = []
        for c in cur:
            if name:
                c = c.get(name) if isinstance(c, dict) else None
            if rest and c is not None:
                idx = rest.rstrip("]")
                if idx == "":
                    nxt.extend(c if isinstance(c, list) else [])
                    fan = True
                    continue
                try:
                    c = c[int(idx)]
                except (IndexError, ValueError, TypeError, KeyError):
                    c = None
            if c is not None:
                nxt.append(c)
        cur = nxt
        if not cur:
            return None
    return cur if fan else cur[0]


def parse_price_range(text: Any) -> tuple[Decimal, Decimal] | None:
    """'US $12.50 - 15' -> (12.50, 15); '9' -> (9, 9). Decimal only."""
    nums = _PRICE_NUM.findall(str(text or ""))
    if not nums:
        return None
    lo, hi = dec(nums[0]), dec(nums[-1])
    return (lo, hi) if lo <= hi else (hi, lo)


class HttpProviderAdapter(SourceAdapter):
    """Config-driven adapter. Subclasses may override build_params / parse hooks."""

    def __init__(
        self,
        config: ProviderConfig,
        client: httpx.AsyncClient | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.config = config
        self.id, self.name, self.mode = config.id, config.name, config.mode
        self.compliance = (
            f"Official/licensed API; >= {MIN_INTERVAL_FLOOR_S:g}s/host; cached; kill-switch; "
            f"off by default. {config.tos_note}".strip()
        )
        self._client = client
        self._env = env if env is not None else os.environ
        kw = {"sleep": sleep} if sleep else {}
        self.limiter = HostRateLimiter(
            max(config.min_interval_s, MIN_INTERVAL_FLOOR_S), clock=clock, **kw
        )
        self.cache = TTLCache(ttl_s=config.cache_ttl_s, clock=clock)

    def __repr__(self) -> str:  # never expose credentials
        return f"<{type(self).__name__} id={self.id} configured={self.configured()}>"

    # ---- state -----------------------------------------------------------
    def api_key(self) -> str:
        return self._env.get(self.config.api_key_env, "") if self.config.api_key_env else ""

    def configured(self) -> bool:
        return bool(self.api_key()) if self.config.api_key_env else True

    def killed(self) -> bool:
        names = [GLOBAL_KILL_SWITCH_ENV, self.config.kill_switch_env]
        return any(n and self._env.get(n, "").strip().lower() in _TRUTHY for n in names)

    # ---- request ----------------------------------------------------------
    def build_params(self, query: SearchQuery) -> dict[str, Any]:
        kw = " ".join(query.keywords_en) or query.q
        return {
            **self.config.extra_params,
            self.config.query_param: kw,
            self.config.limit_param: min(query.limit, 50),
        }

    def build_headers(self) -> dict[str, str]:
        h = {"User-Agent": self.config.user_agent, "Accept": "application/json"}
        if self.config.api_key_env:
            h[self.config.api_key_header] = f"{self.config.api_key_prefix}{self.api_key()}"
        return h

    def search_url(self) -> str:
        return self.config.base_url.rstrip("/") + self.config.search_path

    volatile_params: frozenset[str] = frozenset()  # e.g. timestamp/sign; excluded from cache keys

    def cache_key(self, url: str, params: dict[str, Any]) -> tuple:
        stable = ((k, str(v)) for k, v in params.items() if k not in self.volatile_params)
        return (self.config.method, url, tuple(sorted(stable)))

    async def fetch(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.killed():
            raise ProviderDisabled(f"{self.id}: kill-switch is on")
        if not self.configured():
            raise SourceNotConfigured(f"{self.id}: missing {self.config.api_key_env} (env only)")
        key = self.cache_key(url, params)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        client = self._client or httpx.AsyncClient(timeout=self.config.timeout_s)
        try:
            await self.limiter.wait(urlsplit(url).netloc)
            # streamed with a hard size cap: a hostile/misconfigured provider cannot exhaust memory
            async with client.stream(
                self.config.method, url, params=params, headers=self.build_headers()
            ) as r:
                if r.status_code in (401, 403, 429):
                    raise SourceBlocked(f"{self.id}: HTTP {r.status_code}; not retrying or bypassing")
                r.raise_for_status()
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_RESPONSE_BYTES:
                        raise ValueError(f"{self.id}: response larger than {MAX_RESPONSE_BYTES} bytes")
            data = json.loads(bytes(buf))
        finally:
            if self._client is None:
                await client.aclose()
        self.cache.set(key, data)
        return data

    # ---- mapping ------------------------------------------------------------
    def extract_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = get_path(payload, self.config.results_path)
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
        m = self.config.field_map

        def g(target: str, default: Any = None) -> Any:
            v = get_path(raw, m[target]) if target in m else None
            return default if v in (None, "") else v

        native_id, title = g("id"), g("title")
        if native_id is None or title is None:
            return None
        if "price_range" in m and g("price_range") is not None:
            rng = parse_price_range(g("price_range"))
            lo, hi = rng if rng else (Decimal(0), Decimal(0))
        else:
            lo, hi = g("price_min", 0), g("price_max", g("price_min", 0))
        images = g("images", [])
        moq = g("moq")
        moq_digits = _PRICE_NUM.findall(str(moq)) if moq is not None else []
        return build_listing(
            source=self.id,
            native_id=str(native_id),
            title=str(title),
            price_min=lo,
            price_max=hi,
            currency=str(g("currency", self.config.currency_default)).upper(),
            supplier_native_id=str(g("supplier_id", "")),
            supplier_name=str(g("supplier_name", "")),
            country=str(g("country", self.config.country_default)).upper()[:2],
            city=g("city"),
            url=g("url"),
            images=[str(i) for i in images] if isinstance(images, list) else [str(images)],
            moq=int(dec(moq_digits[0])) if moq_digits else None,
            unit=g("unit"),
            verified=str(g("verified", "")).strip().lower() in {"1", "true", "y", "yes"},
        )

    # ---- SourceAdapter ---------------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        payload = await self.fetch(self.search_url(), self.build_params(query))
        out: list[ListingDetail] = []
        for raw in self.extract_items(payload):
            try:
                item = self.normalize_item(raw)
            except Exception as exc:  # one malformed record must not drop the page
                log.warning("%s: skipped malformed item (%s)", self.id, type(exc).__name__)
                continue
            if item is not None:
                out.append(item)
        return out

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        return None  # provider detail endpoint not wired (UNVERIFIED)

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        return None

    async def health(self) -> Health:
        if self.killed():
            return Health(ok=False, detail="kill-switch on")
        return Health(
            ok=self.configured(), detail="configured" if self.configured() else "not configured"
        )
