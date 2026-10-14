"""Client for the rfq service (deal ownership): Protocol + httpx + deterministic mock."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

import httpx

from ff_payments.domain.errors import UpstreamUnavailable


class NotifyRejected(Exception):
    """rfq refused the callback for good (unknown deal, amount mismatch, bad token): retrying cannot help."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DealClient(Protocol):
    async def get_deal(self, deal_id: str, user_id: str) -> dict[str, Any] | None:
        """The rfq ``Deal`` as seen by ``user_id`` (None when missing or not theirs)."""
        ...

    async def notify_payment_status(self, deal_id: str, payload: dict[str, Any]) -> None:
        """Deliver one settlement event to rfq. Idempotent by ``payload['event_id']``.

        Raises ``UpstreamUnavailable`` when worth retrying (outage, 5xx, 408/429) and ``NotifyRejected``
        for a permanent refusal.
        """
        ...


DealsClient = DealClient  # alias: the rfq-facing client Protocol


class HttpDealClient:
    def __init__(self, base_url: str, internal_token: str | None = None, timeout: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._token = internal_token
        self._c = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def get_deal(self, deal_id: str, user_id: str) -> dict[str, Any] | None:
        headers = {"X-User-Id": user_id}
        if self._token:
            headers["X-Internal-Token"] = self._token
        try:
            r = await self._c.get(f"/v1/deals/{quote(deal_id, safe='')}", headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("RFQ service unavailable") from exc
        if r.status_code in (403, 404):
            return None
        try:
            r.raise_for_status()
            return dict(r.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamUnavailable("RFQ service unavailable") from exc

    async def notify_payment_status(self, deal_id: str, payload: dict[str, Any]) -> None:
        headers = {"X-Internal-Token": self._token} if self._token else {}
        try:
            r = await self._c.post(f"/v1/internal/deals/{quote(deal_id, safe='')}/payment-status", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("RFQ service unavailable") from exc
        if r.status_code >= 500 or r.status_code in (408, 429):
            raise UpstreamUnavailable(f"RFQ answered {r.status_code}")
        if r.status_code >= 400:
            raise NotifyRejected(f"RFQ rejected the callback: {r.status_code} {r.text[:200]}", r.status_code)

    async def aclose(self) -> None:
        await self._c.aclose()


class MockDealClient:
    def __init__(self, deals: dict[str, dict[str, Any]] | None = None) -> None:
        self.deals = deals if deals is not None else {}
        self.notifications = []

    async def get_deal(self, deal_id: str, user_id: str) -> dict[str, Any] | None:
        d = self.deals.get(deal_id)
        return d if d and user_id in (d.get("buyer_id"), d.get("supplier_user_id")) else None

    # ---- callback recording / failure injection (tests, dev) -------------------------------
    notifications: list[dict[str, Any]]
    fail_with: Exception | None = None  # raised by every notify call while set (outage simulation)

    async def notify_payment_status(self, deal_id: str, payload: dict[str, Any]) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.notifications.append({"deal_id": deal_id, **payload})
