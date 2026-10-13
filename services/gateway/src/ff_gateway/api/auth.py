"""Register / login / refresh."""

from fastapi import APIRouter, Request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from ff_gateway.api.deps import to_me
from ff_gateway.db import User
from ff_gateway.domain.errors import (
    AccountDisabled,
    AccountExists,
    InvalidCredentials,
    InvalidToken,
)
from ff_gateway.domain.security import hash_password, verify_password
from ff_gateway.schemas import LoginIn, RefreshIn, RegisterIn, TokensOut

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _tokens(request: Request, user: User, with_user: bool = True) -> TokensOut:
    t = request.app.state.tokens
    return TokensOut(
        access_token=t.access(user.id), refresh_token=t.refresh(user.id), expires_in=t.access_ttl,
        user=to_me(user) if with_user else None,
    )  # fmt: skip


@router.post("/register", response_model=TokensOut, status_code=201)
async def register(body: RegisterIn, request: Request) -> TokensOut:
    sm = request.app.state.sessionmaker
    async with sm() as s:
        if body.email and (await s.scalar(select(User).where(User.email == body.email))):
            raise AccountExists("email")
        if body.phone and (await s.scalar(select(User).where(User.phone == body.phone))):
            raise AccountExists("phone")
        user = User(
            email=body.email, phone=body.phone, name=body.name.strip(),
            password_hash=hash_password(body.password, request.app.state.settings.bcrypt_rounds),
        )  # fmt: skip
        s.add(user)
        try:
            await s.commit()
        except IntegrityError as e:
            raise AccountExists() from e
    return _tokens(request, user)


@router.post("/login", response_model=TokensOut)
async def login(body: LoginIn, request: Request) -> TokensOut:
    conds = []
    if body.email:
        conds.append(User.email == body.email)
    if body.phone:
        conds.append(User.phone == body.phone)
    async with request.app.state.sessionmaker() as s:
        user = await s.scalar(select(User).where(or_(*conds)))
    ok = user is not None and verify_password(body.password, user.password_hash)
    if not ok or user is None:
        raise InvalidCredentials()
    if not user.is_active:
        raise AccountDisabled()
    return _tokens(request, user)


@router.post("/refresh", response_model=TokensOut)
async def refresh(body: RefreshIn, request: Request) -> TokensOut:
    uid = request.app.state.tokens.decode(body.refresh_token, "refresh")
    async with request.app.state.sessionmaker() as s:
        user = await s.get(User, uid)
    if user is None:
        raise InvalidToken("Token refers to an unknown user")
    if not user.is_active:
        raise AccountDisabled()
    return _tokens(request, user, with_user=False)
