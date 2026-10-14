"""In-memory stores: score snapshots (history) and buyer reports (moderation queue).

Process-local by design (this service has no database); both are bounded so they cannot grow without limit.
"""

import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

REPORT_TYPES = ("fraud", "counterfeit", "non_delivery", "quality", "misrepresentation", "unsafe_product", "other")
REPORT_STATUSES = ("pending_review", "accepted", "rejected")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Snapshot:
    at: datetime
    score: int
    band: str
    confidence: int


@dataclass(slots=True)
class Report:
    id: str
    supplier_id: str
    reporter_id: str
    type: str
    text: str
    created_at: datetime
    status: str = "pending_review"
    reviewed_at: datetime | None = None


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


@dataclass
class SnapshotStore:
    max_per_supplier: int = 500
    _data: dict[str, deque[Snapshot]] = field(default_factory=lambda: defaultdict(deque))

    def add(self, supplier_id: str, snap: Snapshot) -> None:
        q = self._data[supplier_id]
        if q and q[-1].score == snap.score and q[-1].band == snap.band and q[-1].confidence == snap.confidence:
            return  # unchanged: do not store duplicates every cache refresh
        q.append(snap)
        while len(q) > self.max_per_supplier:
            q.popleft()

    def list(self, supplier_id: str) -> list[Snapshot]:
        return sorted(self._data.get(supplier_id, ()), key=lambda s: s.at)


class ReportStore:
    def __init__(self, limit: int = 5, window_seconds: int = 3600, clock: Callable[[], datetime] = _now, max_reports: int = 20000, max_users: int = 10000):
        self.limit, self.window, self.clock, self.max_reports = limit, window_seconds, clock, max_reports
        self.max_users = max_users
        self._reports: dict[str, Report] = {}
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def add(self, supplier_id: str, user_id: str, rtype: str, text: str) -> Report:
        """Store a report as pending_review. Raises RateLimited when the user exceeded the window quota."""
        with self._lock:
            now = self.clock()
            if user_id not in self._hits and len(self._hits) >= self.max_users:
                for uid in [u for u, h in self._hits.items() if not h or (now - h[-1]).total_seconds() >= self.window]:
                    del self._hits[uid]
                if len(self._hits) >= self.max_users:  # still full of active users: drop the oldest tracked one
                    del self._hits[next(iter(self._hits))]
            hits = self._hits[user_id]
            while hits and (now - hits[0]).total_seconds() >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimited(max(1, int(self.window - (now - hits[0]).total_seconds())))
            hits.append(now)
            if len(self._reports) >= self.max_reports:
                self._reports.pop(next(iter(self._reports)))
            r = Report(uuid.uuid4().hex, supplier_id, user_id, rtype, text, now)
            self._reports[r.id] = r
            return r

    def get(self, report_id: str) -> Report | None:
        return self._reports.get(report_id)

    def review(self, report_id: str, status: str) -> Report | None:
        """Moderator decision (internal use). Only accepted reports ever influence a score."""
        if status not in ("accepted", "rejected"):
            raise ValueError("status must be accepted or rejected")
        r = self._reports.get(report_id)
        if r is not None:
            r.status, r.reviewed_at = status, self.clock()
        return r

    def accepted_count(self, supplier_id: str) -> int:
        return sum(1 for r in self._reports.values() if r.supplier_id == supplier_id and r.status == "accepted")
