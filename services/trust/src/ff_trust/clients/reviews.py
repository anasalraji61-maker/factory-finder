"""rfq review-summary source: Protocol + httpx client (timeout, short cache, graceful fallback) + deterministic mock."""

import hashlib
import logging
import time
from datetime import datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from ff_trust.domain.signals import ReviewSummary

log = logging.getLogger("ff_trust.reviews")


class ReviewsClient(Protocol):
    name: str

    async def fetch(self, supplier_ref: str) -> ReviewSummary | None:
        """Review aggregates, or None when unavailable (never raises)."""
        ...


def parse_summary(data: object) -> ReviewSummary | None:
    """rfq ReviewSummary JSON (decimals are strings) -> ReviewSummary; None for empty/invalid payloads."""
    if not isinstance(data, dict):
        return None

    def num(v: object) -> float | None:
        try:
            return None if v is None else float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    try:
        count = int(data.get("count") or 0)
        if count <= 0:
            return None
        hist = data.get("histogram")
        hist = {str(k): int(v) for k, v in hist.items()} if isinstance(hist, dict) else None
        subs = data.get("sub_ratings")
        subs = {str(k): num(v) for k, v in subs.items()} if isinstance(subs, dict) else None
        deals = data.get("completed_deals")
        def ts(v: object) -> datetime | None:
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")) if isinstance(v, str) else None
            except ValueError:
                return None

        return ReviewSummary(
            first_review_at=ts(data.get("first_review_at")), last_review_at=ts(data.get("last_review_at")),
            count=count, average=num(data.get("average")), histogram=hist, sub_ratings=subs,
            completed_deals=int(deals) if deals is not None else None,
        )  # fmt: skip
    except (TypeError, ValueError):
        return None


class HttpReviewsClient:
    name = "http"

    def __init__(self, base_url: str, timeout: float = 2.0, cache_ttl: float = 60.0, client: httpx.AsyncClient | None = None, clock=time.monotonic):
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self._ttl, self._clock = cache_ttl, clock
        self._cache: dict[str, tuple[float, ReviewSummary | None]] = {}

    async def fetch(self, supplier_ref: str) -> ReviewSummary | None:
        hit = self._cache.get(supplier_ref)
        if hit and self._clock() < hit[0]:
            return hit[1]
        try:
            r = await self._client.get(f"/v1/suppliers/{quote(supplier_ref, safe='')}/review-summary")
            if r.status_code != 200:
                log.warning("review-summary %s -> HTTP %s", supplier_ref, r.status_code)
                return None  # not cached: retry next time
            out = parse_summary(r.json())
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("review-summary %s failed: %s", supplier_ref, type(exc).__name__)
            return None
        if len(self._cache) >= 2000:
            self._cache.pop(next(iter(self._cache)))
        self._cache[supplier_ref] = (self._clock() + self._ttl, out)
        return out


class MockReviewsClient:
    """Deterministic: curated ids + sha256-derived summaries; `sup_noreviews*` -> None."""

    name = "mock"

    async def fetch(self, supplier_ref: str) -> ReviewSummary | None:
        if supplier_ref.startswith("sup_noreviews"):
            return None
        b = hashlib.sha256(f"{supplier_ref}:reviews".encode()).digest()
        count = b[0] % 60
        if count == 0:
            return None
        avg = round(3.0 + b[1] / 255 * 2.0, 2)
        base = max(1, round(avg))
        hist = {str(i): 0 for i in range(1, 6)}
        for i in range(count):
            hist[str(max(1, min(5, base + (b[2 + i % 20] % 3) - 1)))] += 1
        return ReviewSummary(
            count=count, average=avg, histogram=hist,
            sub_ratings={"quality": round(avg, 2), "communication": None, "shipping": None},
            completed_deals=count // 2,
        )  # fmt: skip
