"""Relay of ``tracking_outbox`` rows to notifications ``POST /v1/internal/tracking-events``.

OFF by default (``FF_TRACKING_NOTIFY_RELAY=on`` + ``FF_TRACKING_NOTIFY_BASE_URL``). The HTTP call sits behind
``NotifyClient`` (real: ``HttpNotifyClient``; tests: ``MockNotifyClient``, no network). Delivery is idempotent
on the notifications side (``dedupe_key``), so replays are harmless.

Per row: ``created``/``duplicate`` -> ``delivered_at``; ``invalid`` -> dead at once (kept for inspection, not
retried); batch failure or a missing result -> attempts+1, exponential backoff, dead after ``max_attempts``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

from ff_tracking.repository import OutboxRow, ShipmentRepository

log = logging.getLogger("ff_tracking.relay")
PATH = "/v1/internal/tracking-events"
USER_AGENT = "FactoryFinder-tracking-relay/0.1"


class NotifyUnavailable(Exception):
    """Transport/HTTP failure for the whole batch (retryable)."""


@dataclass(frozen=True)
class ItemResult:
    dedupe_key: str | None
    status: str  # created | duplicate | invalid
    error: str | None = None


class NotifyClient(Protocol):
    async def send(self, events: list[dict[str, Any]]) -> list[ItemResult]: ...


class HttpNotifyClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = base_url.rstrip("/") + PATH
        self.token, self.timeout, self.transport = token, timeout, transport

    async def send(self, events: list[dict[str, Any]]) -> list[ItemResult]:
        headers = {"User-Agent": USER_AGENT}
        if self.token:
            headers["X-Internal-Token"] = self.token
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as c:
                r = await c.post(self.url, json={"events": events}, headers=headers)
            if r.status_code != 200:
                raise NotifyUnavailable(f"http_{r.status_code}")
            data = r.json()
            return [ItemResult(x.get("dedupe_key"), str(x.get("status")), x.get("error")) for x in data["results"]]
        except NotifyUnavailable:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            raise NotifyUnavailable(type(e).__name__) from e


class MockNotifyClient:
    """Deterministic: ``created`` first time a dedupe_key is seen, ``duplicate`` after; ``invalid`` for keys in
    ``invalid_keys``; raises ``NotifyUnavailable`` while ``fail`` is set. Records every batch in ``calls``."""

    def __init__(self, invalid_keys: set[str] | None = None, fail: bool = False) -> None:
        self.invalid_keys = invalid_keys or set()
        self.fail = fail
        self.seen: set[str] = set()
        self.calls: list[list[dict[str, Any]]] = []

    async def send(self, events: list[dict[str, Any]]) -> list[ItemResult]:
        self.calls.append(events)
        if self.fail:
            raise NotifyUnavailable("mock_down")
        out = []
        for e in events:
            k = e["dedupe_key"]
            if k in self.invalid_keys:
                out.append(ItemResult(k, "invalid", "mock_invalid"))
            elif k in self.seen:
                out.append(ItemResult(k, "duplicate"))
            else:
                self.seen.add(k)
                out.append(ItemResult(k, "created"))
        return out


def _event(row: OutboxRow) -> dict[str, Any]:
    return {"id": row.id, "dedupe_key": row.dedupe_key, "shipment_id": row.shipment_id,
            "owner_id": row.owner_id, "kind": row.kind, "payload": json.loads(row.payload)}


class OutboxRelay:
    def __init__(self, repo: ShipmentRepository, client: NotifyClient, clock: Callable[[], datetime],
                 batch_size: int = 100, max_attempts: int = 8, backoff_base: float = 30.0,
                 backoff_max: float = 3600.0, retention_days: int = 30) -> None:
        self.retention = timedelta(days=max(1, retention_days))
        self._purged_at: datetime | None = None
        self.repo, self.client, self.clock = repo, client, clock
        self.batch_size = max(1, min(batch_size, 100))
        self.max_attempts = max(1, max_attempts)
        self.backoff_base, self.backoff_max = backoff_base, backoff_max

    def backoff(self, attempts: int) -> timedelta:
        return timedelta(seconds=min(self.backoff_base * (2 ** max(attempts - 1, 0)), self.backoff_max))

    async def _fail(self, row: OutboxRow, error: str, now: datetime) -> str:
        attempts = (row.attempts or 0) + 1
        if attempts >= self.max_attempts:
            await self.repo.record_outbox_result(row.id, error=error, dead_at=now)
            return "dead"
        await self.repo.record_outbox_result(row.id, error=error, next_attempt_at=now + self.backoff(attempts))
        return "retry"

    async def run_once(self) -> dict[str, int]:
        now = self.clock()
        if self._purged_at is None or now - self._purged_at >= timedelta(hours=1):
            self._purged_at = now
            try:
                await self.repo.purge_outbox(now - self.retention)
            except Exception:  # retention must never block delivery
                log.exception("tracking outbox purge failed")
        stats = {"sent": 0, "delivered": 0, "invalid": 0, "retried": 0, "dead": 0}
        rows = await self.repo.due_outbox(now, self.batch_size)
        if not rows:
            return stats
        stats["sent"] = len(rows)
        try:
            results = await self.client.send([_event(r) for r in rows])
        except NotifyUnavailable as e:
            for r in rows:
                stats["dead" if await self._fail(r, f"batch:{e}", now) == "dead" else "retried"] += 1
            return stats
        by_key = {x.dedupe_key: x for x in results if x.dedupe_key}
        for r in rows:
            res = by_key.get(r.dedupe_key)
            if res and res.status in ("created", "duplicate"):
                await self.repo.record_outbox_result(r.id, delivered_at=now)
                stats["delivered"] += 1
            elif res and res.status == "invalid":
                await self.repo.record_outbox_result(r.id, error=f"invalid:{res.error or ''}", dead_at=now)
                stats["invalid"] += 1
            else:
                stats["dead" if await self._fail(r, "no_result", now) == "dead" else "retried"] += 1
        return stats

    async def run_forever(self, poll_seconds: float) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # keep the loop alive
                log.exception("tracking relay cycle failed")
            await asyncio.sleep(poll_seconds)


def build_relay(settings, repo: ShipmentRepository, clock: Callable[[], datetime],
                client: NotifyClient | None = None) -> OutboxRelay | None:
    """None unless FF_TRACKING_NOTIFY_RELAY=on and (a client was injected or a base URL is set)."""
    if settings.notify_relay.strip().lower() != "on":
        return None
    if client is None:
        if not settings.notify_base_url:
            log.warning("notify relay is on but FF_TRACKING_NOTIFY_BASE_URL is empty; relay disabled")
            return None
        client = HttpNotifyClient(settings.notify_base_url, settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"),
                                  settings.notify_timeout_seconds)
    return OutboxRelay(repo, client, clock, settings.notify_batch_size, settings.notify_max_attempts,
                       settings.notify_backoff_base_seconds, settings.notify_backoff_max_seconds,
                       settings.outbox_retention_days)
