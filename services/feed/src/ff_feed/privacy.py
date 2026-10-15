"""Account export / erasure (internal token only; see docs/decisions/account-deletion.md).

Erasure: follows, likes and rate counters are deleted; the user's comments become a deleted marker
(body replaced, author tombstoned, status ``deleted`` so they vanish from lists and counts); posts the
user authored are deleted with their likes/comments/reports; the user's reports are kept for moderation
history with the reporter tombstoned.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from ff_feed.db import comments, follows, likes, mutes, posts, rate_events, reports
from ff_feed.service import FeedService

CAP = 1000


def tombstone(user_id: str) -> str:
    return "del_" + hashlib.sha256(("ff-feed:" + user_id).encode()).hexdigest()[:16]


def _iso(d) -> str | None:
    return d.isoformat() if d else None


async def export_user(engine: AsyncEngine, user_id: str) -> dict:
    async with engine.connect() as c:
        ps = (await c.execute(select(posts).where(posts.c.author_user_id == user_id).limit(CAP + 1))).mappings().all()
        cs = (
            await c.execute(
                select(comments).where(comments.c.user_id == user_id, comments.c.status != "deleted").limit(CAP + 1)
            )
        ).mappings().all()
        fs = (await c.execute(select(follows).where(follows.c.user_id == user_id).limit(CAP + 1))).mappings().all()
        ms = (await c.execute(select(mutes).where(mutes.c.user_id == user_id).limit(CAP + 1))).mappings().all()
        ls = (await c.execute(select(likes).where(likes.c.user_id == user_id).limit(CAP + 1))).mappings().all()
        rs = (await c.execute(select(reports).where(reports.c.reporter_id == user_id).limit(CAP + 1))).mappings().all()
    return {
        "truncated": any(len(x) > CAP for x in (ps, cs, fs, ms, ls, rs)),
        "data": {
            "posts": [{"id": p["id"], "supplier_id": p["supplier_id"], "body": p["body"], "media": p["media"],
                       "tags": p["tags"], "status": p["status"], "created_at": _iso(p["created_at"])} for p in ps[:CAP]],
            "comments": [{"id": r["id"], "post_id": r["post_id"], "body": r["body"], "status": r["status"],
                          "created_at": _iso(r["created_at"])} for r in cs[:CAP]],
            "follows": [{"supplier_id": r["supplier_id"], "created_at": _iso(r["created_at"])} for r in fs[:CAP]],
            "mutes": [{"supplier_id": r["supplier_id"], "created_at": _iso(r["created_at"])} for r in ms[:CAP]],
            "likes": [{"post_id": r["post_id"], "created_at": _iso(r["created_at"])} for r in ls[:CAP]],
            "reports": [{"target_type": r["target_type"], "target_id": r["target_id"], "reason": r["reason"],
                         "created_at": _iso(r["created_at"])} for r in rs[:CAP]],
        },
    }  # fmt: skip


async def erase_user(engine: AsyncEngine, user_id: str) -> dict[str, int]:
    tomb = tombstone(user_id)
    counts: dict[str, int] = {}
    async with engine.begin() as c:
        own_posts = [r[0] for r in (await c.execute(select(posts.c.id).where(posts.c.author_user_id == user_id))).all()]
        if own_posts:
            own_comments = [r[0] for r in (await c.execute(select(comments.c.id).where(comments.c.post_id.in_(own_posts)))).all()]
            await c.execute(delete(reports).where(reports.c.target_type == "post", reports.c.target_id.in_(own_posts)))
            if own_comments:
                await c.execute(delete(reports).where(reports.c.target_type == "comment", reports.c.target_id.in_(own_comments)))
            await c.execute(delete(likes).where(likes.c.post_id.in_(own_posts)))
            await c.execute(delete(comments).where(comments.c.post_id.in_(own_posts)))
            await c.execute(delete(posts).where(posts.c.id.in_(own_posts)))
        counts["posts_deleted"] = len(own_posts)
        liked = [r[0] for r in (await c.execute(select(likes.c.post_id).where(likes.c.user_id == user_id))).all()]
        res = await c.execute(delete(likes).where(likes.c.user_id == user_id))
        counts["likes_deleted"] = int(res.rowcount or 0)
        touched = {r[0] for r in (await c.execute(select(comments.c.post_id).where(comments.c.user_id == user_id, comments.c.status != "deleted"))).all()}
        res = await c.execute(
            update(comments).where(comments.c.user_id == user_id, comments.c.status != "deleted")
            .values(user_id=tomb, body="[deleted]", status="deleted", hidden_reason=None)
        )  # fmt: skip
        counts["comments_marked_deleted"] = int(res.rowcount or 0)
        await c.execute(update(comments).where(comments.c.user_id == user_id).values(user_id=tomb))
        res = await c.execute(delete(follows).where(follows.c.user_id == user_id))
        counts["follows_deleted"] = int(res.rowcount or 0)
        res = await c.execute(delete(mutes).where(mutes.c.user_id == user_id))
        counts["mutes_deleted"] = int(res.rowcount or 0)
        res = await c.execute(update(reports).where(reports.c.reporter_id == user_id).values(reporter_id=tomb))
        counts["reports_anonymized"] = int(res.rowcount or 0)
        await c.execute(delete(rate_events).where(rate_events.c.user_id == user_id))
        for pid in set(liked) | touched:  # keep denormalised counters right
            n_likes = await c.scalar(select(func.count()).select_from(likes).where(likes.c.post_id == pid))
            await c.execute(update(posts).where(posts.c.id == pid).values(like_count=n_likes or 0))
            await FeedService._recount(c, pid)
    return counts

