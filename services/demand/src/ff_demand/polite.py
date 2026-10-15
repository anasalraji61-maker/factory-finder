"""Lawful, polite access for any adapter that reads public web pages (CLAUDE.md rule 6).

* sources whose robots/ToS forbid automation are refused before any request,
* robots.txt is honoured per host (cached),
* >= 3 s between requests to the same host (never configurable below that),
* honest ``User-Agent``; never solves CAPTCHAs or logs in.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ff_demand.errors import Forbidden

MIN_INTERVAL = 3.0


@dataclass(frozen=True)
class SourcePolicy:
    name: str
    automated_access_allowed: bool = False  # ToS flag: must be affirmatively True
    robots_disallowed: bool = False


def validate_user_agent(ua: str) -> str:
    """Honest identification: must name a bot; never impersonate a browser/search engine."""
    low = ua.strip().lower()
    impersonated = ("mozilla", "chrome", "safari", "googlebot", "bingbot")
    if "bot" not in low or any(w in low for w in impersonated):
        raise ValueError("User-Agent must identify the bot honestly")
    return ua


def check_source(policy: SourcePolicy | None, blocked: set[str] | None = None) -> None:
    if policy is None or not policy.automated_access_allowed or policy.robots_disallowed:
        raise Forbidden("Source disallows automated access", code="source_disallowed")
    if blocked and policy.name.casefold() in blocked:
        raise Forbidden("Source is switched off", code="source_disallowed")


class PoliteClient:
    def __init__(
        self,
        policy: SourcePolicy | None,
        user_agent: str,
        *,
        client: httpx.AsyncClient,
        min_interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        validate_user_agent(user_agent)
        self.policy, self.user_agent, self.client = policy, user_agent, client
        self.min_interval = max(min_interval, MIN_INTERVAL)
        self._clock, self._sleep = clock, sleep
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._lock = asyncio.Lock()

    async def _wait(self, host: str) -> None:
        async with self._lock:
            last = self._last.get(host)
            if last is not None:
                gap = self.min_interval - (self._clock() - last)
                if gap > 0:
                    await self._sleep(gap)
            self._last[host] = self._clock()

    async def _allowed(self, url: str) -> bool:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(origin)
        if rp is None:
            await self._wait(p.netloc)
            rp = RobotFileParser()
            try:
                resp = await self.client.get(origin + "/robots.txt", headers=self._headers())
            except httpx.HTTPError:
                raise Forbidden(
                    "robots.txt unreachable; failing closed", code="robots_disallowed"
                ) from None
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500 and resp.status_code not in (401, 403, 429):
                rp.parse([])  # 404/410: no robots.txt
            else:  # 401/403/429/3xx/5xx: fail closed
                rp.parse(["User-agent: *", "Disallow: /"])
            self._robots[origin] = rp
        return rp.can_fetch(self.user_agent, url)

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent}

    async def get(self, url: str) -> httpx.Response:
        check_source(self.policy)
        if not await self._allowed(url):
            raise Forbidden("robots.txt disallows this URL", code="robots_disallowed")
        await self._wait(urlsplit(url).netloc)
        return await self.client.get(url, headers=self._headers(), follow_redirects=False)
