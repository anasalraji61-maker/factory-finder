"""Shared plumbing for REAL source adapters (CLAUDE.md rule 6).

Compliance guarantees implemented here:
  * official/licensed APIs preferred; public pages only via an explicit opt-in flag and
    only when robots.txt allows the path (RobotsGuard)
  * per-host rate limit, default >= 3 s between requests (HostRateLimiter)
  * aggressive response caching (TTLCache)
  * honest User-Agent; credentials from env only and never printed (see __repr__)
  * no CAPTCHA / login / paywall bypass: any 401/403/429 or challenge raises SourceBlocked
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel

from ..config import Settings
from ..domain.cache import TTLCache
from ..domain.models import ListingDetail, SearchQuery, Supplier
from .base import Health, SourceAdapter

_VOLATILE = {"timestamp", "sign", "_aop_signature"}  # excluded from cache keys
MIN_INTERVAL_FLOOR_S = 3.0  # CLAUDE.md rule 6: never configurable below this
GLOBAL_KILL_SWITCH_ENV = "FF_SOURCING_KILL_SWITCH"
MAX_RESPONSE_BYTES = 5_000_000
_TRUTHY = {"1", "true", "yes", "on"}


class SourceNotConfigured(RuntimeError):
    pass


class SourceBlocked(RuntimeError):
    pass


class SourceDisabled(RuntimeError):
    """Kill switch is on."""


class HttpRequestSpec(BaseModel):
    method: str = "GET"
    url: str
    params: dict[str, Any] = {}
    headers: dict[str, str] = {}
    kind: str = "api"  # api | page  (page => robots.txt enforced)


class HostRateLimiter:
    def __init__(
        self,
        min_interval_s: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.min_interval_s = max(min_interval_s, MIN_INTERVAL_FLOOR_S)
        self._clock, self._sleep = clock, sleep
        self._next: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> None:
        async with self._lock:
            now = self._clock()
            ready = self._next.get(host, 0.0)
            if ready > now:
                await self._sleep(ready - now)
                now = ready
            self._next[host] = now + self.min_interval_s


class RobotsGuard:
    def __init__(
        self,
        user_agent: str,
        client: httpx.AsyncClient,
        limiter: HostRateLimiter | None = None,
    ):
        self._ua, self._client, self._limiter = user_agent, client, limiter
        self._cache = TTLCache(ttl_s=3600)

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rp = self._cache.get(origin)
        if rp is None:
            rp = RobotFileParser()
            try:
                if self._limiter:
                    await self._limiter.wait(parts.netloc)  # robots fetch is a request too
                r = await self._client.get(f"{origin}/robots.txt", headers={"User-Agent": self._ua})
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif 400 <= r.status_code < 500 and r.status_code not in (401, 403, 429):
                    rp.parse([])  # no robots.txt (404/410): everything allowed
                else:  # 401/403/429/3xx/5xx: fail closed
                    rp.parse(["User-agent: *", "Disallow: /"])
            except httpx.HTTPError:
                rp.parse(["User-agent: *", "Disallow: /"])  # fail closed
            self._cache.set(origin, rp)
        return rp.can_fetch(self._ua, url)


def hmac_sign(params: dict[str, Any], secret: str, algo: str = "sha256", prefix: str = "") -> str:
    """TOP-style signature: HMAC over `prefix + k1v1k2v2...` of sorted params, upper hex."""
    base = prefix + "".join(f"{k}{params[k]}" for k in sorted(params) if k != "sign")
    return hmac.new(secret.encode(), base.encode(), getattr(hashlib, algo)).hexdigest().upper()


class ApiSourceAdapter(SourceAdapter):
    """Skeleton for real adapters. Subclasses implement request building + normalization."""

    mode = "official_api"
    host_note = ""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        limiter: HostRateLimiter | None = None,
    ):
        self.settings = settings
        self._client = client
        self.limiter = limiter or HostRateLimiter(settings.min_request_interval_s)
        self.cache = TTLCache(ttl_s=max(settings.cache_ttl_s, 300.0))
        self._robots: RobotsGuard | None = None
        self._robots_client: httpx.AsyncClient | None = None

    def killed(self) -> bool:
        names = [GLOBAL_KILL_SWITCH_ENV, f"FF_SOURCING_{self.id.upper()}_DISABLED"]
        return any(os.environ.get(n, "").strip().lower() in _TRUTHY for n in names)

    def __repr__(self) -> str:  # never expose credentials
        return f"<{type(self).__name__} id={self.id} configured={self.configured()}>"

    # ---- to implement -------------------------------------------------
    def build_search_request(self, query: SearchQuery) -> HttpRequestSpec:
        raise NotImplementedError

    def parse_search_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail:
        raise NotImplementedError

    # ---- common ---------------------------------------------------------
    async def fetch(self, spec: HttpRequestSpec) -> dict[str, Any]:
        if self.killed():
            raise SourceDisabled(f"{self.id}: kill-switch is on")
        if not self.configured():
            raise SourceNotConfigured(f"{self.id}: missing credentials/config (env only)")
        key = (
            spec.method,
            spec.url,
            tuple(sorted((k, str(v)) for k, v in spec.params.items() if k not in _VOLATILE)),
        )
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        client = self._client or httpx.AsyncClient(timeout=10.0)
        own = self._client is None
        try:
            headers = {"User-Agent": self.settings.user_agent, **spec.headers}
            if spec.kind == "page":
                if self._robots is None or self._robots_client is not client:
                    self._robots = RobotsGuard(self.settings.user_agent, client, self.limiter)
                    self._robots_client = client
                if not await self._robots.allowed(spec.url):
                    raise SourceBlocked(
                        f"{self.id}: robots.txt disallows {urlsplit(spec.url).path}"
                    )
            await self.limiter.wait(urlsplit(spec.url).netloc)
            try:
                r = await client.request(
                    spec.method,
                    spec.url,
                    params=spec.params,
                    headers=headers,
                    follow_redirects=False,
                )
                if r.status_code in (401, 403, 429):
                    raise SourceBlocked(
                        f"{self.id}: HTTP {r.status_code}; not retrying or bypassing"
                    )
                r.raise_for_status()
                if len(r.content) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"{self.id}: response too large")
                try:
                    data = r.json()
                except ValueError:  # HTML challenge / CAPTCHA page: stop, never solve
                    raise SourceBlocked(f"{self.id}: non-JSON response (challenge?); stopping") from None
            except httpx.HTTPError as exc:  # httpx messages embed the URL (signed query): redact
                raise RuntimeError(f"{self.id}: upstream error {type(exc).__name__}") from None
        finally:
            if own:
                await client.aclose()
        self.cache.set(key, data)
        return data

    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        payload = await self.fetch(self.build_search_request(query))
        return [self.normalize_item(r) for r in self.parse_search_response(payload)]

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        return None  # TODO: product-detail endpoint of the provider

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        return None  # TODO: seller-profile endpoint of the provider

    async def health(self) -> Health:
        return Health(
            ok=self.configured(), detail="configured" if self.configured() else "not configured"
        )
