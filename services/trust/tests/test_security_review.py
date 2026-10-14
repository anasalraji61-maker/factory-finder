from datetime import UTC, datetime

from sqlalchemy import func, select

from ff_trust.db import reports
from ff_trust.store import ReportStore


async def test_report_state_is_bounded_against_many_spoofed_user_ids():
    """Rate-limit state is derived from stored reports, which are capped: spoofed ids cannot grow storage."""
    t = [datetime(2026, 10, 1, tzinfo=UTC)]
    s = ReportStore(limit=5, window_seconds=60, clock=lambda: t[0], max_reports=100)
    for i in range(500):
        await s.add("sup_1", f"spoof{i}", "fraud", "x")
    async with s.db.begin() as conn:
        assert (await conn.execute(select(func.count()).select_from(reports))).scalar_one() <= 100
