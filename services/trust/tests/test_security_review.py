from datetime import UTC, datetime

from ff_trust.store import ReportStore


def test_rate_limit_state_is_bounded_against_many_spoofed_user_ids():
    t = [datetime(2026, 10, 1, tzinfo=UTC)]
    s = ReportStore(limit=5, window_seconds=60, clock=lambda: t[0], max_users=100)
    for i in range(500):
        s.add("sup_1", f"spoof{i}", "fraud", "x")
    assert len(s._hits) <= 100
