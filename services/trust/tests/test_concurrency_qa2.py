"""QA2: races on a file-backed sqlite DB (several engines on one file = several processes)."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select

from ff_trust.db import Database, reports
from ff_trust.store import RateLimited, ReportStore, Snapshot, SnapshotStore
from ff_trust.verification import MediaRules, VerificationError, VerificationStore

KEY = "k" * 32
F = "/v1/media/private/abcdef123456.jpg"


def url(p):
    return f"sqlite+aiosqlite:///{p}/trust.db"


async def test_duplicate_reports_same_user_respect_rate_limit(tmp_path):
    stores = [ReportStore(limit=3, window_seconds=3600, db=Database(url(tmp_path), True)) for _ in range(3)]
    res = await asyncio.gather(*[stores[i % 3].add("s", "u1", "fraud", "x") for i in range(12)], return_exceptions=True)
    ok = [r for r in res if not isinstance(r, BaseException)]
    assert len(ok) == 3 and all(isinstance(r, RateLimited) for r in res if isinstance(r, BaseException)), res
    async with stores[0].db.begin() as conn:
        assert (await conn.execute(select(func.count()).select_from(reports))).scalar_one() == 3


async def test_accepted_reports_count_once_per_reporter(tmp_path):
    s = ReportStore(limit=50, db=Database(url(tmp_path), True))
    made = [await s.add("sup", "u1", "fraud", f"t{i}") for i in range(4)]
    await asyncio.gather(*[s.review(r.id, "accepted") for r in made for _ in range(2)])
    assert await s.accepted_count("sup") == 1  # one account cannot multiply its own report


async def test_duplicate_document_submissions_one_wins(tmp_path):
    stores = [VerificationStore(MediaRules(), db=Database(url(tmp_path), True), hash_key=KEY, rate_limit=100) for _ in range(3)]
    args = ("sup", "business_license", "CN", [F], "LIC-AAAA-1", None, True)
    res = await asyncio.gather(*[stores[i % 3].submit(*args) for i in range(6)], return_exceptions=True)
    ok = [r for r in res if not isinstance(r, BaseException)]
    bad = [r for r in res if isinstance(r, BaseException)]
    assert len(ok) == 1 and all(isinstance(b, VerificationError) and b.status == 409 for b in bad), res


async def test_duplicate_snapshots_stored_once(tmp_path):
    ss = [SnapshotStore(Database(url(tmp_path), True)) for _ in range(3)]
    snap = Snapshot(datetime(2026, 10, 1, tzinfo=UTC), 80, "green", 70)
    await asyncio.gather(*[ss[i % 3].add("sup", snap) for i in range(9)])
    assert len(await ss[0].list("sup")) == 1
