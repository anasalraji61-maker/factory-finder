# ruff: noqa: E501
"""QA pass 4: rate-limit races, cursor reuse after deletes, tie stability across pages."""

import asyncio

import pytest
from conftest import post, uh  # noqa: F401
from sqlalchemy import func, select

from ff_feed.config import Settings
from ff_feed.db import likes, make_engine, rate_events
from ff_feed.errors import RateLimited
from ff_feed.schemas import PostCreate
from ff_feed.service import FeedService


@pytest.fixture
async def svc(tmp_path):
    s = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/feed.db", rate_likes=3,
        antispam_author_history=0, antispam_cross_window_hours=0,
        antispam_velocity_posts=0, antispam_velocity_comments=0, rate_posts=0,
    )
    sv = FeedService(make_engine(s.database_url), s)
    await sv.create_all()
    yield sv
    await sv.engine.dispose()


async def test_concurrent_likes_cannot_exceed_rate_limit(svc):
    ids = [(await svc.create_post("owner", "sup_a", PostCreate(body=f"Fresh steel coils lot {i} today")))["id"] for i in range(10)]
    res = await asyncio.gather(*(svc.like("u1", p) for p in ids), return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    bad = [r for r in res if isinstance(r, Exception) and not isinstance(r, RateLimited)]
    assert not bad, bad  # no 500s (locked db etc.)
    assert len(ok) <= 3, len(ok)
    async with svc.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(likes)) == len(ok)
        assert await c.scalar(select(func.count()).select_from(rate_events).where(rate_events.c.action == "likes")) <= 3


def _walk(client, url, limit, between=None):
    seen, cursor = [], None
    for n in range(100):
        page = client.get(f"{url}?limit={limit}" + (f"&cursor={cursor}" if cursor else "")).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            return seen
        if between:
            between(n, seen)
    raise AssertionError("no end")


def test_trending_ties_page_without_dupes_and_survive_deleting_the_cursor_post(client, clock):
    ids = []
    for i in range(9):
        ids.append(post(client, f"tie post number {i}")["id"])
        clock.advance(hours=3)
    clock.advance(hours=30)  # every post is past the freshness boost: all rank 0, ties broken by time/id
    first = client.get("/v1/feed/trending?limit=3").json()
    cursor = first["next_cursor"]
    last_id = first["items"][-1]["id"]
    # the post the cursor points at is deleted by its author before the next page
    r = client.delete(f"/v1/feed/posts/{last_id}", headers={"X-User-Id": "owner", "X-Supplier-Id": "sup_acme"})
    assert r.status_code in (200, 204), r.text
    rest = []
    while cursor:
        page = client.get(f"/v1/feed/trending?limit=3&cursor={cursor}")
        assert page.status_code == 200, page.text
        rest += [i["id"] for i in page.json()["items"]]
        cursor = page.json()["next_cursor"]
    seen = [i["id"] for i in first["items"]] + rest
    assert len(seen) == len(set(seen))
    assert set(ids) - {last_id} <= set(seen)
