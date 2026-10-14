"""Thin routers. Public path prefix /v1/feed (user routes) and /v1/admin/feed (moderation)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from ff_feed.errors import Invalid, NotFound, Unauthenticated
from ff_feed.schemas import ID_RE, SUPPLIER_RE, USER_RE, CommentCreate, HideIn, PostCreate, ReportIn
from ff_feed.service import FeedService

router = APIRouter(prefix="/v1/feed")
admin = APIRouter(prefix="/v1/admin/feed")


def svc(request: Request) -> FeedService:
    return request.app.state.service


def opt_user(request: Request, x_user_id: Annotated[str | None, Header()] = None) -> str | None:
    v = (x_user_id or "").strip()
    if not v:
        return None
    if not USER_RE.match(v):
        raise Unauthenticated("Invalid X-User-Id")
    request.state.user_id = v
    return v


def current_user(user: Annotated[str | None, Depends(opt_user)]) -> str:
    if not user:
        raise Unauthenticated("X-User-Id header is required")
    return user


def verified_supplier(x_supplier_id: Annotated[str | None, Header()] = None) -> str | None:
    """Gateway-verified supplier id (only forwarded for admin-verified claims); never from a body."""
    v = (x_supplier_id or "").strip()
    return v if SUPPLIER_RE.match(v) else None


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    secret = request.app.state.settings.admin_token_value
    if not secret:  # moderation is disabled unless a token is configured
        raise NotFound("Not Found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), secret.encode()):
        raise Unauthenticated("Valid X-Admin-Token required", code="admin_auth_required")


S = Annotated[FeedService, Depends(svc)]
User = Annotated[str, Depends(current_user)]
OptUser = Annotated[str | None, Depends(opt_user)]
Supplier = Annotated[str | None, Depends(verified_supplier)]
Cursor = Annotated[str | None, Query(max_length=300)]
Limit = Annotated[int | None, Query(ge=1, le=50)]
SupplierId = Annotated[str, Path(pattern=SUPPLIER_RE.pattern)]
ObjId = Annotated[str, Path(pattern=ID_RE.pattern, max_length=40)]


# ---- posts
@router.post("/posts", status_code=201)
async def create_post(body: PostCreate, s: S, user: User, supplier: Supplier):
    return await s.create_post(user, supplier, body)


@router.get("/posts/{post_id}")
async def get_post(post_id: ObjId, s: S, user: OptUser):
    return await s.get_post(user, post_id)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: ObjId, s: S, user: User, supplier: Supplier):
    await s.delete_post(user, supplier, post_id)
    return Response(status_code=204)


@router.get("/suppliers/{supplier_id}/posts")
async def supplier_posts(supplier_id: SupplierId, s: S, user: User, cursor: Cursor = None, limit: Limit = None):
    return await s.supplier_posts(user, supplier_id, cursor, limit)


# ---- feeds
@router.get("/home")
async def home(s: S, user: User, cursor: Cursor = None, limit: Limit = None):
    return await s.home(user, cursor, limit)


@router.get("/trending")
async def trending(s: S, user: OptUser, cursor: Cursor = None, limit: Limit = None):
    return await s.trending(user, cursor, limit)


# ---- follows
@router.get("/following")
async def following(s: S, user: User, cursor: Cursor = None, limit: Limit = None):
    return await s.following(user, cursor, limit)


@router.post("/suppliers/{supplier_id}/follow")
async def follow(supplier_id: SupplierId, s: S, user: User, supplier: Supplier):
    return await s.follow(user, supplier, supplier_id)


@router.delete("/suppliers/{supplier_id}/follow")
async def unfollow(supplier_id: SupplierId, s: S, user: User):
    return await s.unfollow(user, supplier_id)


# ---- likes
@router.put("/posts/{post_id}/like")
async def like(post_id: ObjId, s: S, user: User):
    return await s.like(user, post_id)


@router.delete("/posts/{post_id}/like")
async def unlike(post_id: ObjId, s: S, user: User):
    return await s.unlike(user, post_id)


# ---- comments
@router.get("/posts/{post_id}/comments")
async def list_comments(post_id: ObjId, s: S, user: User, cursor: Cursor = None, limit: Limit = None):
    return await s.list_comments(post_id, cursor, limit)


@router.post("/posts/{post_id}/comments", status_code=201)
async def add_comment(post_id: ObjId, body: CommentCreate, s: S, user: User):
    return await s.add_comment(user, post_id, body)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: ObjId, s: S, user: User, supplier: Supplier):
    await s.delete_comment(user, supplier, comment_id)
    return Response(status_code=204)


# ---- reports (identical 202 for first and repeated reports)
@router.post("/posts/{post_id}/report", status_code=202)
async def report_post(post_id: ObjId, body: ReportIn, s: S, user: User, supplier: Supplier):
    return await s.report(user, "post", post_id, body.reason, body.details, supplier)


@router.post("/comments/{comment_id}/report", status_code=202)
async def report_comment(comment_id: ObjId, body: ReportIn, s: S, user: User):
    return await s.report(user, "comment", comment_id, body.reason, body.details, None)


# ---- admin moderation (X-Admin-Token; 404 when FF_FEED_ADMIN_TOKEN is unset)
Status = Annotated[str, Query(pattern="^(published|hidden|all)$")]


@admin.get("/posts", dependencies=[Depends(require_admin)])
async def admin_posts(s: S, status: Status = "hidden", cursor: Cursor = None, limit: Limit = None):
    return await s.admin_posts(status, cursor, limit)


@admin.post("/posts/{post_id}/hide", dependencies=[Depends(require_admin)])
async def admin_hide_post(post_id: ObjId, body: HideIn, s: S):
    return await s.admin_set_post(post_id, True, body.reason)


@admin.post("/posts/{post_id}/restore", dependencies=[Depends(require_admin)])
async def admin_restore_post(post_id: ObjId, s: S):
    return await s.admin_set_post(post_id, False, None)


@admin.get("/comments", dependencies=[Depends(require_admin)])
async def admin_comments(
    s: S, status: Status = "hidden", post_id: Annotated[str | None, Query(pattern=ID_RE.pattern)] = None,
    cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.admin_comments(status, post_id, cursor, limit)


@admin.post("/comments/{comment_id}/hide", dependencies=[Depends(require_admin)])
async def admin_hide_comment(comment_id: ObjId, body: HideIn, s: S):
    return await s.admin_set_comment(comment_id, True, body.reason)


@admin.post("/comments/{comment_id}/restore", dependencies=[Depends(require_admin)])
async def admin_restore_comment(comment_id: ObjId, s: S):
    return await s.admin_set_comment(comment_id, False, None)


@admin.get("/reports", dependencies=[Depends(require_admin)])
async def admin_reports(
    s: S, target_type: Annotated[str | None, Query(pattern="^(post|comment)$")] = None,
    target_id: Annotated[str | None, Query(pattern=ID_RE.pattern)] = None,
    cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.admin_reports(target_type, target_id, cursor, limit)


__all__ = ["Invalid", "admin", "router"]
