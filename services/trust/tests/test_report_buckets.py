from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from ff_trust.config import Settings
from ff_trust.db import Database
from ff_trust.main import create_app
from ff_trust.store import CapacityReached, ReportStore

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def store(**kw):
    return ReportStore(limit=100, window_seconds=60, clock=lambda: T0, db=Database("sqlite+aiosqlite:///:memory:", True), **kw)


async def test_low_trust_flood_never_evicts_established_reports():
    s = store(max_reports=5, max_low_trust=3)
    est = [await s.add("s", f"e{i}", "fraud", "x") for i in range(2)]
    low = [await s.add("s", f"l{i}", "fraud", "x", low_trust=True) for i in range(3)]
    for i in range(20):  # flood: only the low bucket recycles
        await s.add("s", f"f{i}", "fraud", "x", low_trust=True)
    assert all([await s.get(r.id) for r in est])
    assert await s.get(low[0].id) is None


async def test_low_trust_bucket_cap_and_oldest_rejected_first():
    s = store(max_reports=100, max_low_trust=2)
    a = await s.add("s", "a", "fraud", "x", low_trust=True)
    b = await s.add("s", "b", "fraud", "x", low_trust=True)
    await s.review(b.id, "rejected")
    await s.add("s", "c", "fraud", "x", low_trust=True)
    assert await s.get(b.id) is None and await s.get(a.id) is not None


async def test_full_of_accepted_low_rows_refuses_low_but_not_established_room():
    s = store(max_reports=3, max_low_trust=2)
    for i in range(2):
        x = await s.add("s", f"l{i}", "fraud", "x", low_trust=True)
        await s.review(x.id, "accepted")
    with pytest.raises(CapacityReached):  # low bucket is all evidence: refuse rather than evict it
        await s.add("s", "l9", "fraud", "x", low_trust=True)
    assert (await s.add("s", "e1", "fraud", "x")).low_trust is False  # established still has room


async def test_established_evicts_low_pending_before_established_pending():
    s = store(max_reports=3, max_low_trust=3)
    e = await s.add("s", "e1", "fraud", "x")
    low = await s.add("s", "l1", "fraud", "x", low_trust=True)
    await s.add("s", "e2", "fraud", "x")
    await s.add("s", "e3", "fraud", "x")
    assert await s.get(low.id) is None and await s.get(e.id) is not None


def mk(**kw):
    s = Settings(report_min_account_age_seconds=1000, **kw)
    return TestClient(create_app(s))


def post(c, uid, **h):
    return c.post("/v1/trust/suppliers/sup_1/report", json={"type": "fraud", "text": "x"}, headers={"X-User-Id": uid, **h})


def test_headers_classify_and_absent_headers_unchanged():
    with mk(report_max_low_trust=100, report_max_total=1000) as c:
        svc = c.app.state.service
        ids = {}
        for uid, h in {"a": {}, "b": {"X-Account-Age-Seconds": "5000", "X-Email-Verified": "1"}, "c": {"X-Account-Age-Seconds": "10", "X-Email-Verified": "1"},
                       "d": {"X-Account-Age-Seconds": "5000", "X-Email-Verified": "0"}, "e": {"X-Account-Age-Seconds": "abc"}, "f": {"X-Email-Verified": "maybe"}}.items():
            r = post(c, uid, **h)
            assert r.status_code == 201, (uid, r.text)
            ids[uid] = r.json()["id"]
        got = {u: c.portal.call(svc.reports.get, i).low_trust for u, i in ids.items()}
        assert got == {"a": False, "b": False, "c": True, "d": True, "e": True, "f": True}
