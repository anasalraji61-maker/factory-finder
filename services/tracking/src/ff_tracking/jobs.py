"""Background refresh of active shipments, at most every ``interval_hours`` per shipment."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from ff_tracking.repository import ShipmentRepository
from ff_tracking.service import ProviderFailed, ShipmentService

log = logging.getLogger("ff_tracking.jobs")


class RefreshJob:
    def __init__(self, repo: ShipmentRepository, service: ShipmentService, clock: Callable[[], datetime],
                 interval_hours: float = 6.0, batch_size: int = 50) -> None:
        self.repo, self.service, self.clock = repo, service, clock
        self.interval = timedelta(hours=interval_hours)
        self.batch_size = batch_size
        self._lock = asyncio.Lock()  # overlapping runs would double-fetch and overwrite each other's saves

    async def run_once(self) -> dict[str, int]:
        async with self._lock:
            return await self._run_once()

    async def _run_once(self) -> dict[str, int]:
        now = self.clock()
        due = await self.repo.due_for_refresh(now - self.interval, self.batch_size)
        stats = {"refreshed": 0, "failed": 0, "events": 0}
        for sh in due:
            try:
                stats["events"] += await self.service.refresh_system(sh)
                stats["refreshed"] += 1
            except ProviderFailed:
                stats["failed"] += 1
            except Exception:  # one broken shipment must not stop the others
                log.exception("tracking refresh failed for one shipment")
                stats["failed"] += 1
        return stats

    async def run_forever(self, poll_seconds: float) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # keep the loop alive; one bad cycle must not stop tracking
                log.exception("tracking refresh cycle failed")
            await asyncio.sleep(max(1.0, poll_seconds))  # never a tight loop, even if misconfigured
