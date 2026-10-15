"""Performance regressions: trending must stay bounded (query count, index use) and exact."""

import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert, text

from ff_feed.config import Settings
from ff_feed.db import comments, follows, likes, make_engine, metadata, posts
from ff_feed.service import FRESH_BOOST, FRESH_HOURS, FeedService

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


async def _seed(n=600):
    e = make_engine("sqlite+aiosqlite:///:memory:")
    async with e.begin() as c:
        await c.run_sync(metadata.create_all)
    r = random.Random(7)
    P, L, C = [], [], []
    for i in range(n):
        pid = f"p{i:05d}"
        auth = f"o{i % 30}"
        age = timedelta(minutes=r.randint(0, 60 * 24 * 8))
        users = r.sample(range(200), min(int(r.paretovariate(1.2)) - 1, 40))
        ext_l = [u for u in users if f"u{u}" != auth]
        nc = r.randint(0, 3)
        L += [dict(post_id=pid, user_id=f"u{u}", created_at=NOW - timedelta(minutes=1)) for u in users]
        C += [dict(id=f"c{i}_{k}", post_id=pid, user_id=f"u{k}", body="x", status="published", report_count=0,
                   created_at=NOW - timedelta(minutes=1)) for k in range(nc)]
        P.append(dict(id=pid, supplier_id=f"s{i % 30}", author_user_id=auth, body="b", media=[], tags=[],
                      status="published", like_count=len(users), comment_count=nc, report_count=0,
                      score=len(ext_l) + 2 * nc, created_at=NOW - age))
    async with e.begin() as c:
        for t, rows in ((posts, P), (likes, L), (comments, C)):
            await c.execute(insert(t), rows)
    return e, P, L, C


def _expected(P, L, C, settings):
    since = NOW - timedelta(days=settings.trending_window_days)
    out = []
    for p in P:
        if not (since <= p["created_at"] <= NOW):
            continue
        lk = sum(1 for x in L if x["post_id"] == p["id"] and x["user_id"] != p["author_user_id"])
        cm = sum(1 for x in C if x["post_id"] == p["id"] and x["user_id"] != p["author_user_id"])
        fresh = FRESH_BOOST if p["created_at"] > NOW - timedelta(hours=FRESH_HOURS) else 0
        out.append((lk + 2 * cm + fresh, p["created_at"], p["id"]))
    return [i for _, _, i in sorted(out, reverse=True)]


def test_trending_pruned_matches_exact_ranking_and_is_bounded():
    async def go():
        e, P, L, C = await _seed()
        s = Settings(database_url="sqlite+aiosqlite:///:memory:")
        svc = FeedService(e, s, clock=lambda: NOW)
        want = _expected(P, L, C, s)
        n = [0]
        event.listen(e.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))
        seen, cursor, pages = [], None, 0
        while True:
            n[0] = 0
            page = await svc.trending("u1", cursor, 20)
            if pages == 0:
                assert n[0] <= 8, n[0]  # was 2 queries, but scanned the whole window; stays O(rounds)
            seen += [i["id"] for i in page["items"]]
            cursor, pages = page["next_cursor"], pages + 1
            if not cursor or pages >= 4:
                break
        assert seen == want[: len(seen)]
        assert len(seen) == 20 * pages

    asyncio.run(go())


def test_trending_candidate_scan_uses_score_index_without_sort():
    async def go():
        e, *_ = await _seed(50)
        sql = (
            "EXPLAIN QUERY PLAN SELECT id, score FROM posts WHERE status='published' AND created_at>='2026' "
            "AND created_at<='2027' ORDER BY score DESC LIMIT 400"
        )
        async with e.connect() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(sql))).all())
        assert "ix_posts_status_score" in plan and "TEMP B-TREE" not in plan

    asyncio.run(go())


def test_home_following_uses_index_and_fixed_query_count():
    async def go():
        e, *_ = await _seed(300)
        async with e.begin() as c:
            await c.execute(insert(follows), [dict(user_id="b", supplier_id="s3", created_at=NOW)])
        svc = FeedService(e, Settings(database_url="sqlite+aiosqlite:///:memory:"), clock=lambda: NOW)
        n = [0]
        event.listen(e.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))
        page = await svc.home("b", None, 10)
        assert page["source"] == "following" and n[0] == 2  # page + liked-set, no per-post queries

    asyncio.run(go())
