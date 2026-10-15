"""Admin review of supplier claims (disabled unless FF_GATEWAY_ADMIN_TOKEN is set)."""

import hmac
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.db import DeletionJob, User
from ff_gateway.domain.errors import BEARER_REALM, GatewayError

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
    page: int = Query(1, ge=1),
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


async def _decide(request: Request, user_id: str, approve: bool) -> dict:
    require_admin(request)
    async with request.app.state.sessionmaker() as s:
        u = await s.get(User, user_id)
        if u is None:
            raise StarletteHTTPException(404, "User not found")
        if u.supplier_claim_status != "pending" or not u.supplier_id:
            raise ClaimNotPending()
        if approve:
            u.supplier_claim_status = "verified"
        else:  # reject releases the id so it can be claimed again
            u.supplier_claim_status = "none"
            u.supplier_id = None
        await s.commit()
        return _claim(u)


@router.post("/v1/admin/supplier-claims/{user_id}/approve")
async def approve_claim(user_id: str, request: Request) -> dict:
    return await _decide(request, user_id, True)


@router.post("/v1/admin/supplier-claims/{user_id}/reject")
async def reject_claim(user_id: str, request: Request) -> dict:
    return await _decide(request, user_id, False)


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
