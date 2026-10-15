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
import logging
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

log = logging.getLogger(__name__)
# httpx logs every request URL at INFO, including signed query strings / api keys: keep it quiet.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
_VOLATILE = {"timestamp", "sign", "_aop_signature"}  # excluded from cache keys
MIN_INTERVAL_FLOOR_S = 3.0  # CLAUDE.md rule 6: never configurable below this
GLOBAL_KILL_SWITCH_ENV = "FF_SOURCING_KILL_SWITCH"
MAX_RESPONSE_BYTES = 5_000_000
_TRUTHY = {"1", "true", "yes", "on"}


def validate_user_agent(ua: str) -> str:
    """Honest identification (rule 6): must name a bot, never impersonate a browser/search engine."""
    low = ua.strip().lower()
    if "bot" not in low or any(w in low for w in ("mozilla", "chrome", "safari", "googlebot", "bingbot")):
        raise ValueError("user_agent must identify this bot honestly (e.g. FactoryFinderBot/0.1 (+url))")
    return ua


class SourceNotConfigured(RuntimeError):
    pass


class SourceBlocked(RuntimeError):
    """Upstream refused us (401/403/429/challenge). Never retried or bypassed.

    ``retry_after_s`` is set for 429 (Retry-After header honoured, or DEFAULT_COOLDOWN_S).
    """

    def __init__(self, message: str = "", retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


DEFAULT_COOLDOWN_S = 60.0
MAX_COOLDOWN_S = 3600.0


def parse_retry_after(value: str | None, now_epoch: float | None = None) -> float | None:
    """Retry-After as delta-seconds or HTTP-date -> seconds (>= 0), or None when absent/garbage."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return float(v)
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - (time.time() if now_epoch is None else now_epoch))


def cooldown_seconds(retry_after: str | None) -> float:
    secs = parse_retry_after(retry_after)
    return min(secs if secs is not None else DEFAULT_COOLDOWN_S, MAX_COOLDOWN_S)


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
        self._cool: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def cool_down(self, host: str, seconds: float) -> None:
        """A 429 said 'back off': no request to ``host`` until ``seconds`` have passed."""
        self._cool[host] = max(self._cool.get(host, 0.0), self._clock() + max(0.0, seconds))

    def cooldown_remaining(self, host: str) -> float:
        return max(0.0, self._cool.get(host, 0.0) - self._clock())

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

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
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
            host = urlsplit(spec.url).netloc
            if (left := self.limiter.cooldown_remaining(host)) > 0:
                raise SourceBlocked(f"{self.id}: cooling down after HTTP 429", retry_after_s=left)
            await self.limiter.wait(host)
            try:
                r = await client.request(
                    spec.method,
                    spec.url,
                    params=spec.params,
                    headers=headers,
                    follow_redirects=False,
                )
                if r.status_code == 429:
                    secs = cooldown_seconds(r.headers.get("retry-after"))
                    self.limiter.cool_down(host, secs)
                    raise SourceBlocked(
                        f"{self.id}: HTTP 429; not retrying, cooling down {secs:g}s",
                        retry_after_s=secs,
                    )
                if r.status_code in (401, 403):
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
                if not isinstance(data, dict):
                    raise SourceBlocked(f"{self.id}: unexpected JSON shape; stopping") from None
            except httpx.HTTPError as exc:  # httpx messages embed the URL (signed query): redact
                raise RuntimeError(f"{self.id}: upstream error {type(exc).__name__}") from None
        finally:
            if own:
                await client.aclose()
        self.cache.set(key, data)
        return data

    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        payload = await self.fetch(self.build_search_request(query))
        out: list[ListingDetail] = []
        seen: set[str] = set()
        for raw in self.parse_search_response(payload):
            try:  # one malformed record must not drop the page
                item = self.normalize_item(raw) if isinstance(raw, dict) else None
            except Exception as exc:
                log.warning("%s: skipped malformed item (%s)", self.id, type(exc).__name__)
                continue
            if item is not None and item.id not in seen:  # providers repeat items across/within pages
                seen.add(item.id)
                out.append(item)
        return out

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        return None  # TODO: product-detail endpoint of the provider

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        return None  # TODO: seller-profile endpoint of the provider

    async def health(self) -> Health:
        return Health(
            ok=self.configured(), detail="configured" if self.configured() else "not configured"
        )
