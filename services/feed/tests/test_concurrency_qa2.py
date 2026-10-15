"""QA pass 2: races on a file-backed SQLite database (real concurrent connections)."""

import asyncio

import pytest
from sqlalchemy import func, select

from ff_feed.config import Settings
from ff_feed.db import follows, likes, make_engine, posts, reports
from ff_feed.errors import ApiError
from ff_feed.schemas import CommentCreate, PostCreate
from ff_feed.service import FeedService

SUP = "sup_acme"


@pytest.fixture
async def svc(tmp_path):
    s = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/feed.db",
        report_min_account_age_seconds=0,
        rate_likes=0, rate_follows=0, rate_reports=0, rate_posts=0, rate_comments=0,
        antispam_author_history=0, antispam_cross_window_hours=0,
        antispam_velocity_posts=0, antispam_velocity_comments=0,
    )
    sv = FeedService(make_engine(s.database_url), s)
    await sv.create_all()
    yield sv
    await sv.engine.dispose()


async def _post(svc):
    return (await svc.create_post("owner", SUP, PostCreate(body="Fresh steel coils in stock today")))["id"]


async def _gather(coros):
    return await asyncio.gather(*coros, return_exceptions=True)


async def test_double_like_counts_once(svc):
    pid = await _post(svc)
    res = await _gather([svc.like("u1", pid) for _ in range(8)])
    assert not [r for r in res if isinstance(r, Exception)], res
    async with svc.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(likes)) == 1
        assert await c.scalar(select(posts.c.like_count)) == 1
        assert await c.scalar(select(posts.c.score)) == 1


async def test_like_unlike_race_keeps_counter_consistent(svc):
    pid = await _post(svc)
    await _gather([svc.like("u1", pid), svc.unlike("u1", pid)] * 5 + [svc.like(f"u{i}", pid) for i in range(2, 6)])
    async with svc.engine.connect() as c:
        n = await c.scalar(select(func.count()).select_from(likes))
        assert await c.scalar(select(posts.c.like_count)) == n >= 4


async def test_double_follow_and_unfollow(svc):
    res = await _gather([svc.follow("u1", None, "sup_beta") for _ in range(8)])
    assert not [r for r in res if isinstance(r, Exception)], res
    assert all(r["follower_count"] == 1 for r in res)
    res = await _gather([svc.unfollow("u1", "sup_beta") for _ in range(4)])
    assert not [r for r in res if isinstance(r, Exception)], res
    async with svc.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(follows)) == 0


async def test_double_report_one_row_and_threshold_needs_distinct_reporters(svc):
    pid = await _post(svc)
    res = await _gather([svc.report("r1", "post", pid, "spam", None, None) for _ in range(8)])
    assert not [r for r in res if isinstance(r, Exception)], res
    async with svc.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(reports)) == 1
        assert await c.scalar(select(posts.c.status)) == "published"  # one reporter never hides
    await _gather([svc.report(f"r{i}", "post", pid, "spam", None, None) for i in range(2, 5)])
    async with svc.engine.connect() as c:
        assert await c.scalar(select(posts.c.status)) == "hidden"
        assert await c.scalar(select(posts.c.report_count)) >= 3


async def test_concurrent_comments_count_exact(svc):
    pid = await _post(svc)
    res = await _gather([svc.add_comment(f"u{i}", pid, CommentCreate(body=f"Interested in price {i}")) for i in range(10)])
    assert not [r for r in res if isinstance(r, Exception)], res
    async with svc.engine.connect() as c:
        assert await c.scalar(select(posts.c.comment_count)) == 10


async def test_hidden_post_leaks_nothing_via_unlike_or_like(svc):
    pid = await _post(svc)
    await svc.like("u1", pid)
    await svc.admin_set_post(pid, True, "x")
    for fn in (svc.like, svc.unlike):
        with pytest.raises(ApiError):
            await fn("u2", pid)
