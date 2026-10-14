"""Business logic. Every public method is one request; counters are kept in the same transaction."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ff_feed import cursor as cur
from ff_feed.config import Settings
from ff_feed.db import comments, follows, likes, now, posts, rate_events, reports
from ff_feed.errors import Conflict, Forbidden, Invalid, NotFound, RateLimited
from ff_feed.moderation import redact, screen_fields
from ff_feed.schemas import SUPPLIER_RE, CommentCreate, PostCreate

MEDIA_PATH_RE = re.compile(r"/v1/media/files/[a-f0-9]{32}\.(?:jpg|png|webp)")


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond:06d}Z"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class FeedService:
    def __init__(self, engine: AsyncEngine, settings: Settings, clock: Callable[[], datetime] = now):
        self.engine, self.s, self.clock = engine, settings, clock

    # ------------------------------------------------------------------ helpers
    async def create_all(self) -> None:
        from ff_feed.db import metadata

        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    def _limit(self, limit: int | None) -> int:
        return max(1, min(limit or self.s.default_page_size, self.s.max_page_size))

    async def _rate(self, user: str, action: str) -> None:
        """Rolling-window limit, stored in the DB so it holds across replicas. Counted even when the
        request is later rejected (screening), so the banned-term list cannot be probed."""
        limit = getattr(self.s, f"rate_{action}")
        if limit == 0:
            return
        t = self.clock()
        window = timedelta(seconds=self.s.rate_window_seconds)
        where = and_(rate_events.c.user_id == user, rate_events.c.action == action)
        async with self.engine.begin() as c:
            await c.execute(delete(rate_events).where(where, rate_events.c.created_at < t - window))
            rows = (
                await c.execute(
                    select(rate_events.c.created_at)
                    .where(where)
                    .order_by(rate_events.c.created_at)
                    .limit(limit)
                )
            ).all()
            if len(rows) >= limit:
                wait = max(1, math.ceil((rows[0][0] + window - t).total_seconds()))
                raise RateLimited(
                    "Too many requests, slow down",
                    code="rate_limited",
                    details={"action": action, "limit": limit, "retry_after_seconds": wait},
                    headers={"Retry-After": str(wait)},
                )
            await c.execute(insert(rate_events).values(user_id=user, action=action, created_at=t))

    def _media(self, urls: list[str]) -> list[str]:
        base = (self.s.media_base_url or "").rstrip("/")
        out: list[str] = []
        for u in urls:
            u = u.strip()
            if u.startswith("/"):
                path = u
            elif base and u.startswith(base + "/"):
                path = u[len(base) :]
            else:
                path = ""
            if not MEDIA_PATH_RE.fullmatch(path):
                raise Invalid(
                    "media must be image URLs served by the media service (/v1/media/files/<id>.<ext>)",
                    code="invalid_media",
                )
            if u not in out:
                out.append(u)
        return out

    @staticmethod
    def _screen(fields: dict[str, str | None]) -> None:
        flags = screen_fields(fields)
        if flags:
            reasons = sorted({f.message for f in flags})[:4]
            raise Invalid(
                "Content not allowed: remove contact details, links and prohibited items",
                code="content_rejected",
                details={"reasons": reasons},
            )

    @staticmethod
    def _post(r, liked: set[str], admin: bool = False) -> dict:
        d = {
            "id": r.id,
            "supplier_id": r.supplier_id,
            "body": r.body,
            "media": r.media,
            "tags": r.tags,
            "listing_ref": r.listing_ref,
            "like_count": r.like_count,
            "comment_count": r.comment_count,
            "viewer_liked": r.id in liked,
            "created_at": _iso(r.created_at),
        }
        if admin:
            d |= {
                "status": r.status,
                "hidden_reason": r.hidden_reason,
                "report_count": r.report_count,
                "author_user_id": r.author_user_id,
            }
        return d

    @staticmethod
    def _comment(r, admin: bool = False) -> dict:
        d = {"id": r.id, "post_id": r.post_id, "user_id": r.user_id, "body": r.body,
             "created_at": _iso(r.created_at)}  # fmt: skip
        if admin:
            d |= {"status": r.status, "hidden_reason": r.hidden_reason, "report_count": r.report_count}
        return d

    async def _liked(self, c, user: str | None, ids: list[str]) -> set[str]:
        if not user or not ids:
            return set()
        rows = await c.execute(
            select(likes.c.post_id).where(likes.c.user_id == user, likes.c.post_id.in_(ids))
        )
        return {r[0] for r in rows}

    async def _post_page(self, c, q, user: str | None, limit: int, kind: str, admin=False) -> dict:
        rows = (await c.execute(q.limit(limit + 1))).all()
        more = len(rows) > limit
        rows = rows[:limit]
        liked = await self._liked(c, user, [r.id for r in rows])
        nxt = None
        if more and rows:
            last = rows[-1]
            nxt = cur.encode(kind, last.created_at, last.id, last.score if kind == "t" else None)
        return {"items": [self._post(r, liked, admin) for r in rows], "next_cursor": nxt}

    # ------------------------------------------------------------------ posts
    async def create_post(self, user: str, supplier: str | None, body: PostCreate) -> dict:
        if not supplier:
            raise Forbidden("A verified supplier account is required to post", code="supplier_required")
        media = self._media(body.media)
        await self._rate(user, "posts")
        self._screen({"body": body.body, "tags": " ".join(body.tags)})
        pid, t = _new_id("post"), self.clock()
        async with self.engine.begin() as c:
            n = await c.scalar(
                select(func.count()).select_from(posts).where(posts.c.supplier_id == supplier)
            )
            if (n or 0) >= self.s.max_posts_per_supplier:
                raise Conflict(
                    "Post limit reached; delete an old post first", code="post_limit_reached"
                )
            await c.execute(
                insert(posts).values(
                    id=pid, supplier_id=supplier, author_user_id=user, body=body.body, media=media,
                    tags=body.tags, listing_ref=body.listing_ref, status="published",
                    like_count=0, comment_count=0, report_count=0, score=0, created_at=t,
                )  # fmt: skip
            )
            r = (await c.execute(select(posts).where(posts.c.id == pid))).one()
        return self._post(r, set())

    async def _visible_post(self, c, post_id: str):
        r = (
            await c.execute(select(posts).where(posts.c.id == post_id, posts.c.status == "published"))
        ).first()
        if r is None:
            raise NotFound("Post not found")
        return r

    async def get_post(self, user: str | None, post_id: str) -> dict:
        async with self.engine.connect() as c:
            r = await self._visible_post(c, post_id)
            return self._post(r, await self._liked(c, user, [post_id]))

    async def delete_post(self, user: str, supplier: str | None, post_id: str) -> None:
        async with self.engine.begin() as c:
            r = (await c.execute(select(posts.c.supplier_id).where(posts.c.id == post_id))).first()
            if r is None:
                raise NotFound("Post not found")
            if not supplier or supplier != r[0]:
                raise Forbidden("Only the publishing supplier can delete this post")
            cids = select(comments.c.id).where(comments.c.post_id == post_id)
            await c.execute(delete(reports).where(reports.c.target_type == "comment", reports.c.target_id.in_(cids)))
            await c.execute(delete(reports).where(reports.c.target_type == "post", reports.c.target_id == post_id))
            await c.execute(delete(comments).where(comments.c.post_id == post_id))
            await c.execute(delete(likes).where(likes.c.post_id == post_id))
            await c.execute(delete(posts).where(posts.c.id == post_id))

    async def supplier_posts(self, user: str | None, supplier_id: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(posts).where(posts.c.supplier_id == supplier_id, posts.c.status == "published")
        q = self._after_time(q, cursor)
        async with self.engine.connect() as c:
            return await self._post_page(c, q, user, limit, "c")

    @staticmethod
    def _after_time(q, cursor: str | None, kind: str = "c", table=posts):
        """Newest-first keyset: rows strictly older than (created_at, id) of the cursor."""
        if cursor:
            d = cur.decode(cursor, (kind,))
            q = q.where(
                or_(
                    table.c.created_at < d["t"],
                    and_(table.c.created_at == d["t"], table.c.id < d["i"]),
                )
            )
        return q.order_by(table.c.created_at.desc(), table.c.id.desc())

    # ------------------------------------------------------------------ feeds
    async def trending(self, user: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        since = self.clock() - timedelta(days=self.s.trending_window_days)
        q = select(posts).where(posts.c.status == "published", posts.c.created_at >= since)
        if cursor:
            d = cur.decode(cursor, ("t",))
            q = q.where(
                or_(
                    posts.c.score < d["s"],
                    and_(posts.c.score == d["s"], posts.c.created_at < d["t"]),
                    and_(posts.c.score == d["s"], posts.c.created_at == d["t"], posts.c.id < d["i"]),
                )
            )
        q = q.order_by(posts.c.score.desc(), posts.c.created_at.desc(), posts.c.id.desc())
        async with self.engine.connect() as c:
            page = await self._post_page(c, q, user, limit, "t")
        return {**page, "source": "trending"}

    async def home(self, user: str, cursor: str | None, limit: int | None) -> dict:
        kind = cur.decode(cursor, ("f", "t"))["k"] if cursor else "f"
        if kind == "t":
            return await self.trending(user, cursor, limit)
        limit = self._limit(limit)
        followed = select(follows.c.supplier_id).where(follows.c.user_id == user)
        q = select(posts).where(posts.c.status == "published", posts.c.supplier_id.in_(followed))
        if cursor:
            d = cur.decode(cursor, ("f",))
            q = q.where(
                or_(
                    posts.c.created_at < d["t"],
                    and_(posts.c.created_at == d["t"], posts.c.id < d["i"]),
                )
            )
        q = q.order_by(posts.c.created_at.desc(), posts.c.id.desc())
        async with self.engine.connect() as c:
            page = await self._post_page(c, q, user, limit, "f")
        if not page["items"] and not cursor:  # follows nobody, or nothing new: fall back
            return await self.trending(user, None, limit)
        return {**page, "source": "following"}

    # ------------------------------------------------------------------ follows
    async def follow(self, user: str, own_supplier: str | None, supplier_id: str) -> dict:
        if own_supplier == supplier_id:
            raise Invalid("You cannot follow your own supplier account", code="cannot_follow_self")
        await self._rate(user, "follows")
        try:
            async with self.engine.begin() as c:
                have = await c.scalar(
                    select(func.count()).select_from(follows).where(
                        follows.c.user_id == user, follows.c.supplier_id == supplier_id
                    )
                )
                if not have:
                    n = await c.scalar(
                        select(func.count()).select_from(follows).where(follows.c.user_id == user)
                    )
                    if (n or 0) >= self.s.max_follows_per_user:
                        raise Conflict("Follow limit reached; unfollow someone first", code="follow_limit_reached")
                    await c.execute(
                        insert(follows).values(user_id=user, supplier_id=supplier_id, created_at=self.clock())
                    )
        except IntegrityError:
            pass  # concurrent duplicate follow: already following
        return {"supplier_id": supplier_id, "following": True, "follower_count": await self._followers(supplier_id)}

    async def unfollow(self, user: str, supplier_id: str) -> dict:
        await self._rate(user, "follows")
        async with self.engine.begin() as c:
            await c.execute(delete(follows).where(follows.c.user_id == user, follows.c.supplier_id == supplier_id))
        return {"supplier_id": supplier_id, "following": False, "follower_count": await self._followers(supplier_id)}

    async def _followers(self, supplier_id: str) -> int:
        async with self.engine.connect() as c:
            return (await c.scalar(select(func.count()).select_from(follows).where(follows.c.supplier_id == supplier_id))) or 0

    async def following(self, user: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(follows.c.supplier_id, follows.c.created_at).where(follows.c.user_id == user)
        if cursor:
            d = cur.decode(cursor, ("s",))
            q = q.where(
                or_(
                    follows.c.created_at < d["t"],
                    and_(follows.c.created_at == d["t"], follows.c.supplier_id < d["i"]),
                )
            )
        q = q.order_by(follows.c.created_at.desc(), follows.c.supplier_id.desc()).limit(limit + 1)
        async with self.engine.connect() as c:
            rows = (await c.execute(q)).all()
        more, rows = len(rows) > limit, rows[:limit]
        nxt = cur.encode("s", rows[-1].created_at, rows[-1].supplier_id) if more else None
        return {
            "items": [{"supplier_id": r.supplier_id, "followed_at": _iso(r.created_at)} for r in rows],
            "next_cursor": nxt,
        }

    # ------------------------------------------------------------------ likes
    async def like(self, user: str, post_id: str) -> dict:
        await self._rate(user, "likes")
        try:
            async with self.engine.begin() as c:
                await self._visible_post(c, post_id)
                have = await c.scalar(
                    select(func.count()).select_from(likes).where(likes.c.post_id == post_id, likes.c.user_id == user)
                )
                if not have:
                    await c.execute(insert(likes).values(post_id=post_id, user_id=user, created_at=self.clock()))
                    await c.execute(
                        update(posts).where(posts.c.id == post_id)
                        .values(like_count=posts.c.like_count + 1, score=posts.c.score + 1)
                    )  # fmt: skip
        except IntegrityError:
            pass  # concurrent duplicate like: the winner already counted it
        return await self._like_state(user, post_id)

    async def unlike(self, user: str, post_id: str) -> dict:
        await self._rate(user, "likes")
        async with self.engine.begin() as c:
            if (await c.scalar(select(func.count()).select_from(posts).where(posts.c.id == post_id))) == 0:
                raise NotFound("Post not found")
            res = await c.execute(delete(likes).where(likes.c.post_id == post_id, likes.c.user_id == user))
            if res.rowcount:
                await c.execute(
                    update(posts).where(posts.c.id == post_id, posts.c.like_count > 0)
                    .values(like_count=posts.c.like_count - 1, score=posts.c.score - 1)
                )  # fmt: skip
        return await self._like_state(user, post_id)

    async def _like_state(self, user: str, post_id: str) -> dict:
        async with self.engine.connect() as c:
            n = await c.scalar(select(posts.c.like_count).where(posts.c.id == post_id))
            mine = await c.scalar(
                select(func.count()).select_from(likes).where(likes.c.post_id == post_id, likes.c.user_id == user)
            )
        return {"post_id": post_id, "liked": bool(mine), "like_count": n or 0}

    # ------------------------------------------------------------------ comments
    async def add_comment(self, user: str, post_id: str, body: CommentCreate) -> dict:
        async with self.engine.connect() as c:
            await self._visible_post(c, post_id)
        await self._rate(user, "comments")
        self._screen({"body": body.body})
        cid = _new_id("cmt")
        async with self.engine.begin() as c:
            p = await self._visible_post(c, post_id)
            if p.comment_count >= self.s.max_comments_per_post:
                raise Conflict("This post has reached its comment limit", code="comment_limit_reached")
            await c.execute(
                insert(comments).values(
                    id=cid, post_id=post_id, user_id=user, body=body.body, status="published",
                    report_count=0, created_at=self.clock(),
                )  # fmt: skip
            )
            await c.execute(
                update(posts).where(posts.c.id == post_id)
                .values(comment_count=posts.c.comment_count + 1, score=posts.c.score + 2)
            )  # fmt: skip
            r = (await c.execute(select(comments).where(comments.c.id == cid))).one()
        return self._comment(r)

    async def list_comments(self, post_id: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(comments).where(comments.c.post_id == post_id, comments.c.status == "published")
        if cursor:
            d = cur.decode(cursor, ("c",))
            q = q.where(
                or_(
                    comments.c.created_at > d["t"],
                    and_(comments.c.created_at == d["t"], comments.c.id > d["i"]),
                )
            )
        q = q.order_by(comments.c.created_at, comments.c.id).limit(limit + 1)
        async with self.engine.connect() as c:
            await self._visible_post(c, post_id)
            rows = (await c.execute(q)).all()
        more, rows = len(rows) > limit, rows[:limit]
        nxt = cur.encode("c", rows[-1].created_at, rows[-1].id) if more else None
        return {"items": [self._comment(r) for r in rows], "next_cursor": nxt}

    async def delete_comment(self, user: str, supplier: str | None, comment_id: str) -> None:
        async with self.engine.begin() as c:
            r = (
                await c.execute(
                    select(comments.c.user_id, comments.c.post_id, comments.c.status, posts.c.supplier_id)
                    .select_from(comments.join(posts, posts.c.id == comments.c.post_id))
                    .where(comments.c.id == comment_id)
                )
            ).first()
            if r is None:
                raise NotFound("Comment not found")
            if r.user_id != user and not (supplier and supplier == r.supplier_id):
                raise Forbidden("Only the author or the post's supplier can delete this comment")
            await c.execute(delete(reports).where(reports.c.target_type == "comment", reports.c.target_id == comment_id))
            await c.execute(delete(comments).where(comments.c.id == comment_id))
            await self._recount(c, r.post_id)

    @staticmethod
    async def _recount(c, post_id: str) -> None:
        n = await c.scalar(
            select(func.count()).select_from(comments).where(comments.c.post_id == post_id, comments.c.status == "published")
        )
        await c.execute(
            update(posts).where(posts.c.id == post_id).values(comment_count=n or 0, score=posts.c.like_count + 2 * (n or 0))
        )

    # ------------------------------------------------------------------ reports
    async def report(self, user: str, kind: str, target_id: str, reason: str, details: str | None, own_supplier: str | None) -> dict:
        tbl = posts if kind == "post" else comments
        async with self.engine.connect() as c:
            row = (await c.execute(select(tbl).where(tbl.c.id == target_id))).first()
        if row is None or row.status != "published":
            raise NotFound("Post not found" if kind == "post" else "Comment not found")
        if (kind == "post" and own_supplier == row.supplier_id) or (kind == "comment" and row.user_id == user):
            raise Invalid("You cannot report your own content", code="cannot_report_own")
        await self._rate(user, "reports")
        clean = redact(details.strip())[:300] if details and details.strip() else None
        try:
            async with self.engine.begin() as c:
                dup = await c.scalar(
                    select(func.count()).select_from(reports).where(
                        reports.c.target_type == kind, reports.c.target_id == target_id, reports.c.reporter_id == user
                    )
                )
                if dup:
                    return {"status": "received"}
                await c.execute(
                    insert(reports).values(
                        id=_new_id("rep"), target_type=kind, target_id=target_id, reporter_id=user,
                        reason=reason, details=clean, created_at=self.clock(),
                    )  # fmt: skip
                )
                n = await c.scalar(
                    select(func.count()).select_from(reports).where(reports.c.target_type == kind, reports.c.target_id == target_id)
                )
                vals: dict = {"report_count": n}
                hide = n >= self.s.report_hide_threshold
                if hide:
                    vals |= {"status": "hidden", "hidden_reason": "auto: report threshold reached"}
                await c.execute(update(tbl).where(tbl.c.id == target_id, tbl.c.status == "published").values(**vals))
                if hide and kind == "comment":
                    await self._recount(c, row.post_id)
        except IntegrityError:
            pass  # concurrent identical report
        return {"status": "received"}

    # ------------------------------------------------------------------ admin
    async def admin_posts(self, status: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(posts)
        if status != "all":
            q = q.where(posts.c.status == status)
        q = self._after_time(q, cursor)
        async with self.engine.connect() as c:
            return await self._post_page(c, q, None, limit, "c", admin=True)

    async def admin_set_post(self, post_id: str, hide: bool, reason: str | None) -> dict:
        async with self.engine.begin() as c:
            if not (await c.scalar(select(func.count()).select_from(posts).where(posts.c.id == post_id))):
                raise NotFound("Post not found")
            if hide:
                vals = {"status": "hidden", "hidden_reason": f"admin: {reason}"[:300]}
            else:  # restore: previous reports no longer count toward the threshold
                vals = {"status": "published", "hidden_reason": None, "report_count": 0}
                await c.execute(delete(reports).where(reports.c.target_type == "post", reports.c.target_id == post_id))
            await c.execute(update(posts).where(posts.c.id == post_id).values(**vals))
            r = (await c.execute(select(posts).where(posts.c.id == post_id))).one()
        return self._post(r, set(), admin=True)

    async def admin_comments(self, status: str, post_id: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(comments)
        if status != "all":
            q = q.where(comments.c.status == status)
        if post_id:
            q = q.where(comments.c.post_id == post_id)
        q = self._after_time(q, cursor, table=comments)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
        more, rows = len(rows) > limit, rows[:limit]
        nxt = cur.encode("c", rows[-1].created_at, rows[-1].id) if more else None
        return {"items": [self._comment(r, admin=True) for r in rows], "next_cursor": nxt}

    async def admin_set_comment(self, comment_id: str, hide: bool, reason: str | None) -> dict:
        async with self.engine.begin() as c:
            row = (await c.execute(select(comments).where(comments.c.id == comment_id))).first()
            if row is None:
                raise NotFound("Comment not found")
            if hide:
                vals = {"status": "hidden", "hidden_reason": f"admin: {reason}"[:300]}
            else:
                vals = {"status": "published", "hidden_reason": None, "report_count": 0}
                await c.execute(delete(reports).where(reports.c.target_type == "comment", reports.c.target_id == comment_id))
            await c.execute(update(comments).where(comments.c.id == comment_id).values(**vals))
            await self._recount(c, row.post_id)
            r = (await c.execute(select(comments).where(comments.c.id == comment_id))).one()
        return self._comment(r, admin=True)

    async def admin_reports(self, target_type: str | None, target_id: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(reports)
        if target_type:
            q = q.where(reports.c.target_type == target_type)
        if target_id:
            q = q.where(reports.c.target_id == target_id)
        q = self._after_time(q, cursor, table=reports)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
        more, rows = len(rows) > limit, rows[:limit]
        nxt = cur.encode("c", rows[-1].created_at, rows[-1].id) if more else None
        items = [
            {"id": r.id, "target_type": r.target_type, "target_id": r.target_id, "reporter_id": r.reporter_id,
             "reason": r.reason, "details": r.details, "created_at": _iso(r.created_at)}
            for r in rows
        ]  # fmt: skip
        return {"items": items, "next_cursor": nxt}


def valid_supplier(v: str) -> bool:
    return bool(SUPPLIER_RE.match(v))
