"""Client for the trust service (GET /v1/trust/suppliers/{id}). Failures degrade to 'unknown'."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Protocol
from urllib.parse import quote

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
    # optional: ``async def get_many(ids) -> dict[str, TrustInfo]`` (one round trip); callers fall back to ``get``


BATCH_MAX = 50  # trust service limit per /suppliers:batch call


def _info(supplier_id: str, body: dict) -> TrustInfo:
    band = body.get("band", "unknown")
    if band not in ("green", "yellow", "red", "unknown"):
        band = "unknown"
    return TrustInfo(supplier_id=supplier_id, score=body.get("score"), band=band)


class HttpTrustClient:
    def __init__(
        self, base_url: str, timeout_s: float = 0.8, client: httpx.AsyncClient | None = None
    ):
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client
        self._shared: httpx.AsyncClient | None = None  # pooled keep-alive client, created on first use

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._shared is None:  # a client per lookup cost a fresh connection (and SSL context) every time
            self._shared = httpx.AsyncClient(timeout=self._timeout, limits=httpx.Limits(max_connections=32))
        return self._shared

    async def aclose(self) -> None:
        if self._shared is not None:
            c, self._shared = self._shared, None
            await c.aclose()

    async def get_many(self, supplier_ids: list[str]) -> dict[str, TrustInfo]:
        """One ``/suppliers:batch`` call per 50 ids. Ids the service does not know, and every id of a failed
        chunk, come back as 'unknown' (callers must not cache those), exactly like ``get``."""
        ids = [i for i in dict.fromkeys(supplier_ids) if "," not in i]  # a comma cannot travel in the id list
        out: dict[str, TrustInfo] = {}
        odd = [i for i in dict.fromkeys(supplier_ids) if "," in i]
        if odd:
            out.update(zip(odd, await asyncio.gather(*(self.get(i) for i in odd)), strict=True))
        for i in range(0, len(ids), BATCH_MAX):
            chunk = ids[i : i + BATCH_MAX]
            try:
                r = await self._http().get(
                    f"{self._base}/v1/trust/suppliers:batch", params={"ids": ",".join(chunk)}, timeout=self._timeout
                )
                known: dict[str, TrustInfo] = {}
                if r.status_code == 200:
                    for row in r.json().get("items", []):
                        sid = row.get("supplier_id")
                        if sid in chunk:
                            known[sid] = _info(sid, row)
                    out.update({sid: known.get(sid) or unknown(sid) for sid in chunk})
                    continue
            except Exception as exc:
                log.warning("trust batch lookup failed: %s", type(exc).__name__)
            # batch unavailable (old service, ids with commas, outage): the per-id path decides
            out.update(zip(chunk, await asyncio.gather(*(self.get(sid) for sid in chunk)), strict=True))
        return out

    async def get(self, supplier_id: str) -> TrustInfo:
        url = f"{self._base}/v1/trust/suppliers/{quote(supplier_id, safe='')}"
        try:
            r = await self._http().get(url, timeout=self._timeout)
            if r.status_code != 200:
                return unknown(supplier_id)
            return _info(supplier_id, r.json())
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
