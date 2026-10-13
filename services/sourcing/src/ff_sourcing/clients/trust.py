"""Client for the trust service (GET /v1/trust/suppliers/{id}). Failures degrade to 'unknown'."""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

import httpx
from pydantic import BaseModel

from ..domain.models import TrustBand

log = logging.getLogger(__name__)


class TrustInfo(BaseModel):
    supplier_id: str
    score: int | None = None
    band: TrustBand = "unknown"


def unknown(supplier_id: str) -> TrustInfo:
    return TrustInfo(supplier_id=supplier_id)


class TrustClient(Protocol):
    async def get(self, supplier_id: str) -> TrustInfo: ...


class HttpTrustClient:
    def __init__(
        self, base_url: str, timeout_s: float = 0.8, client: httpx.AsyncClient | None = None
    ):
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client

    async def get(self, supplier_id: str) -> TrustInfo:
        url = f"{self._base}/v1/trust/suppliers/{supplier_id}"
        try:
            if self._client is not None:
                r = await self._client.get(url, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    r = await c.get(url)
            if r.status_code != 200:
                return unknown(supplier_id)
            body = r.json()
            band = body.get("band", "unknown")
            if band not in ("green", "yellow", "red", "unknown"):
                band = "unknown"
            return TrustInfo(supplier_id=supplier_id, score=body.get("score"), band=band)
        except Exception as exc:  # network, timeout, bad json: never break search
            log.warning("trust lookup failed for %s: %s", supplier_id, type(exc).__name__)
            return unknown(supplier_id)


class MockTrustClient:
    """Deterministic score from the supplier id hash; `overrides` pins specific ids."""

    def __init__(self, overrides: dict[str, TrustInfo] | None = None):
        self._overrides = overrides or {}

    async def get(self, supplier_id: str) -> TrustInfo:
        if supplier_id in self._overrides:
            return self._overrides[supplier_id]
        h = int(hashlib.sha256(supplier_id.encode()).hexdigest()[:8], 16)
        score = 40 + h % 56
        band = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        return TrustInfo(supplier_id=supplier_id, score=score, band=band)


class NullTrustClient:
    async def get(self, supplier_id: str) -> TrustInfo:
        return unknown(supplier_id)
