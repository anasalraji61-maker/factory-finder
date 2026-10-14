"""Admin review of supplier claims (disabled unless FF_GATEWAY_ADMIN_TOKEN is set)."""

import hmac
from typing import Literal

from fastapi import APIRouter, Request
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.db import User
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
async def list_claims(request: Request, status: Literal["pending", "verified"] = "pending") -> dict:
    require_admin(request)
    async with request.app.state.sessionmaker() as s:
        rows = (
            await s.scalars(
                select(User)
                .where(User.supplier_claim_status == status, User.supplier_id.is_not(None))
                .order_by(User.created_at)
            )
        ).all()
    return {"items": [_claim(u) for u in rows]}


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
