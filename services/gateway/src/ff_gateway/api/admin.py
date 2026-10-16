"""Admin review of supplier claims (disabled unless FF_GATEWAY_ADMIN_TOKEN is set)."""

import hmac
import re
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.db import ClaimDecision, DeletionJob, User
from ff_gateway.domain import privacy
from ff_gateway.domain.errors import BEARER_REALM, GatewayError, ValidationFailed
from ff_gateway.domain.trust_release import release_supplier

router = APIRouter(tags=["admin"])


class ClaimNotPending(GatewayError):
    status_code = 409
    code = "claim_not_pending"
    default_message = "This user has no pending supplier claim"


class AdminAuthRequired(GatewayError):
    status_code = 401
    code = "admin_auth_required"
    default_message = "Valid X-Admin-Token required"
    default_headers = {"WWW-Authenticate": BEARER_REALM}


def require_admin(request: Request) -> None:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise StarletteHTTPException(404, "Not Found")
    given = request.headers.get("x-admin-token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise AdminAuthRequired()


def _claim(u: User) -> dict:
    return {
        "user_id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "company": u.company,
        "supplier_id": u.supplier_id, "supplier_claim_status": u.supplier_claim_status,
    }  # fmt: skip


@router.get("/v1/admin/supplier-claims")
async def list_claims(
    request: Request,
    status: Literal["pending", "verified"] = "pending",
    page: int = Query(1, ge=1, le=1_000_000),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    require_admin(request)
    cond = (User.supplier_claim_status == status, User.supplier_id.is_not(None))
    async with request.app.state.sessionmaker() as s:
        rows = (
            await s.scalars(
                select(User)
                .where(*cond)
                .order_by(User.created_at, User.id)
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
        total = await s.scalar(select(func.count()).select_from(User).where(*cond))
    return {"items": [_claim(u) for u in rows], "total": total, "page": page, "page_size": limit}


_REVIEWER_BAD = re.compile(r"[^A-Za-z0-9_.:-]")
MAX_REASON = 500


def sanitize_reviewer(raw: str | None) -> str:
    """Audit label from the optional X-Reviewer header: charset-restricted (so no '@' / emails), <= 64 chars, else 'admin'."""
    return _REVIEWER_BAD.sub("", raw or "")[:64] or "admin"


class ClaimNotVerified(GatewayError):
    status_code = 409
    code = "claim_not_verified"
    default_message = "This user has no verified supplier claim"


async def _reason(request: Request, required: bool) -> str | None:
    raw = await request.body()
    data = None
    if raw.strip():
        try:
            data = await request.json()
        except ValueError:
            raise ValidationFailed.for_field("reason", "body must be JSON") from None
    if data is not None and not isinstance(data, dict):
        raise ValidationFailed.for_field("reason", "body must be a JSON object")
    reason = (data or {}).get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ValidationFailed.for_field("reason", "reason must be a string")
    reason = reason.strip() if reason else None
    if required and not reason:
        raise ValidationFailed.for_field("reason", "reason is required")
    if reason and len(reason) > MAX_REASON:
        raise ValidationFailed.for_field("reason", f"reason must be at most {MAX_REASON} characters")
    return reason or None


async def _decide(request: Request, user_id: str, action: str) -> dict:
    require_admin(request)
    reason = await _reason(request, required=action == "revoke")
    reviewer = sanitize_reviewer(request.headers.get("x-reviewer"))
    async with request.app.state.sessionmaker() as s:
        u = await s.get(User, user_id)
        if u is None:
            raise StarletteHTTPException(404, "User not found")
        before = u.supplier_claim_status
        if action == "revoke":
            if before != "verified" or not u.supplier_id:
                raise ClaimNotVerified()
        elif before != "pending" or not u.supplier_id:
            raise ClaimNotPending()
        sid = u.supplier_id
        if action == "approve":
            u.supplier_claim_status = "verified"
        else:  # reject / revoke release the id so it can be claimed again (after fresh approval)
            u.supplier_claim_status = "none"
            u.supplier_id = None
        s.add(ClaimDecision(
            user_id=u.id, supplier_id=sid, action=action, previous_status=before, new_status=u.supplier_claim_status,
            reviewer=reviewer, reason=reason, created_at=request.app.state.clock.now(),
        ))  # fmt: skip
        await s.commit()
        out = _claim(u)
    privacy.drop_active_cache(request.app, user_id)  # X-Supplier-Id is read per request; drop the 5 s active cache too
    if action in ("reject", "revoke"):  # best-effort: hide the old claimant's documents from the next claimant
        await release_supplier(request.app, request, sid, f"claim {action}", reviewer)
    return out


@router.post("/v1/admin/supplier-claims/{user_id}/approve")
async def approve_claim(user_id: str, request: Request) -> dict:
    return await _decide(request, user_id, "approve")


@router.post("/v1/admin/supplier-claims/{user_id}/reject")
async def reject_claim(user_id: str, request: Request) -> dict:
    return await _decide(request, user_id, "reject")


@router.post("/v1/admin/supplier-claims/{user_id}/revoke")
async def revoke_claim(user_id: str, request: Request) -> dict:
    return await _decide(request, user_id, "revoke")


@router.get("/v1/admin/supplier-claims/audit")
async def claim_audit(request: Request, user_id: str | None = Query(None, max_length=40), limit: int = Query(100, ge=1, le=500)) -> dict:
    """Append-only decision log, newest first."""
    require_admin(request)
    q = select(ClaimDecision).order_by(ClaimDecision.id.desc()).limit(limit)
    if user_id:
        q = q.where(ClaimDecision.user_id == user_id)
    async with request.app.state.sessionmaker() as s:
        rows = (await s.scalars(q)).all()
    return {"items": [
        {"id": r.id, "user_id": r.user_id, "supplier_id": r.supplier_id, "action": r.action, "previous_status": r.previous_status,
         "new_status": r.new_status, "reviewer": r.reviewer, "reason": r.reason, "created_at": r.created_at.isoformat()} for r in rows
    ]}  # fmt: skip


@router.get("/v1/admin/account-deletions")
async def list_deletion_jobs(request: Request, status: Literal["pending", "dead"] = "pending", limit: int = Query(100, ge=1, le=500)) -> dict:
    """Erasure jobs that have not completed (opaque ids and short error codes only; no PII)."""
    require_admin(request)
    async with request.app.state.sessionmaker() as s:
        rows = (await s.scalars(select(DeletionJob).where(DeletionJob.status == status).order_by(DeletionJob.id).limit(limit))).all()
    return {"items": [
        {"user_id": j.user_id, "service": j.service, "status": j.status, "attempts": j.attempts,
         "last_error": j.last_error, "next_attempt_at": j.next_attempt_at.isoformat()} for j in rows
    ]}  # fmt: skip
