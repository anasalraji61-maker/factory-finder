"""Shared request helpers."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ff_gateway.db import User
from ff_gateway.domain.errors import AccountDisabled, AuthenticationRequired, InvalidToken
from ff_gateway.schemas import Location, MeOut


def bearer_token(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    scheme, _, token = h.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def current_user_id(request: Request) -> str:
    token = bearer_token(request)
    if token is None:
        raise AuthenticationRequired()
    return request.app.state.tokens.decode(token, "access")


async def current_user(request: Request) -> User:
    uid = current_user_id(request)
    async with request.app.state.sessionmaker() as s:
        user = await s.get(User, uid)
    if user is None:
        raise InvalidToken("Token refers to an unknown user")
    if not user.is_active:
        raise AccountDisabled()
    return user


def to_me(u: User) -> MeOut:
    return MeOut(
        id=u.id, name=u.name, email=u.email, phone=u.phone, company=u.company, role=u.role,  # type: ignore[arg-type]
        default_destination=Location(**u.default_destination) if u.default_destination else None,
        supplier_id=u.supplier_id, supplier_claim_status=u.supplier_claim_status or "none",  # type: ignore[arg-type]
        display_currency=u.display_currency, language=u.language, created_at=u.created_at,  # type: ignore[arg-type]
    )  # fmt: skip


def internal_headers(request: Request, user_id: str | None) -> dict[str, str]:
    """Headers the gateway adds towards upstream services."""
    h = {"X-Request-Id": getattr(request.state, "request_id", "")}
    if user_id:
        h["X-User-Id"] = user_id
    token = request.app.state.settings.internal_token
    if token:
        h["X-Internal-Token"] = token
    return h


__all__ = [
    "AsyncSession",
    "bearer_token",
    "current_user",
    "current_user_id",
    "internal_headers",
    "to_me",
]
