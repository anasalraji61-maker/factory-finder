"""Register / login / refresh."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from ff_gateway.api.deps import to_me
from ff_gateway.db import RefreshToken, User
from ff_gateway.domain.errors import (
    AccountDisabled,
    AccountExists,
    InvalidCredentials,
    InvalidToken,
)
from ff_gateway.domain.security import hash_jti, hash_password, verify_password
from ff_gateway.schemas import LoginIn, RefreshIn, RegisterIn, TokensOut

router = APIRouter(prefix="/v1/auth", tags=["auth"])
_DUMMY_HASH = hash_password("timing-equalizer", 12)


async def _tokens(
    request: Request, user: User, with_user: bool = True, family: str | None = None
) -> TokensOut:
    """Issue an access + refresh pair; the refresh token's jti is recorded (hashed) under its family."""
    t = request.app.state.tokens
    refresh, c = t.new_refresh(user.id, family)
    async with request.app.state.sessionmaker() as s:
        s.add(RefreshToken(
            jti_hash=hash_jti(c.jti), user_id=user.id, family=c.family,
            expires_at=datetime.fromtimestamp(c.expires_at, UTC),
        ))  # fmt: skip
        await s.commit()
    return TokensOut(
        access_token=t.access(user.id), refresh_token=refresh, expires_in=t.access_ttl,
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
    return await _tokens(request, user)


@router.post("/login", response_model=TokensOut)
async def login(body: LoginIn, request: Request) -> TokensOut:
    conds = []
    if body.email:
        conds.append(User.email == body.email)
    if body.phone:
        conds.append(User.phone == body.phone)
    async with request.app.state.sessionmaker() as s:
        user = await s.scalar(select(User).where(or_(*conds)))
    # always run a bcrypt check so unknown accounts are not distinguishable by response time
    ok = (
        verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        and user is not None
    )
    if not ok or user is None:
        raise InvalidCredentials()
    if not user.is_active:
        raise AccountDisabled()
    return await _tokens(request, user)


@router.post("/refresh", response_model=TokensOut)
async def refresh(body: RefreshIn, request: Request) -> TokensOut:
    """Rotate: each refresh token is single-use. Replaying a used one revokes the whole family."""
    app = request.app
    c = app.state.tokens.decode_refresh(body.refresh_token)
    now = app.state.clock.now()
    key = hash_jti(c.jti)
    async with app.state.sessionmaker() as s:
        row = await s.get(RefreshToken, key)
        if row is None or row.revoked_at is not None or row.user_id != c.user_id:
            raise InvalidToken("Refresh token is no longer valid")
        # atomic claim: only one concurrent request can flip used_at from NULL
        res = await s.execute(
            update(RefreshToken)
            .where(RefreshToken.jti_hash == key, RefreshToken.used_at.is_(None))
            .values(used_at=now)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 0:  # already used -> theft suspected: kill the family
            await s.execute(
                update(RefreshToken)
                .where(RefreshToken.family == row.family, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
                .execution_options(synchronize_session=False)
            )
            await s.commit()
            raise InvalidToken("Refresh token was already used; please sign in again")
        user = await s.get(User, c.user_id)
        if user is None:
            await s.commit()
            raise InvalidToken("Token refers to an unknown user")
        if not user.is_active:
            await s.commit()
            raise AccountDisabled()
        await s.execute(
            delete(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.expires_at < now)
            .execution_options(synchronize_session=False)
        )
        await s.commit()
    return await _tokens(request, user, with_user=False, family=c.family)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, request: Request) -> Response:
    """Revoke the refresh token's whole family. Always 204 (idempotent; no token oracle)."""
    try:
        c = request.app.state.tokens.decode_refresh(body.refresh_token, check_exp=False)
    except InvalidToken:
        return Response(status_code=204)
    async with request.app.state.sessionmaker() as s:
        row = await s.get(RefreshToken, hash_jti(c.jti))
        if row is not None and row.user_id == c.user_id:
            await s.execute(
                update(RefreshToken)
                .where(RefreshToken.family == row.family, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=request.app.state.clock.now())
                .execution_options(synchronize_session=False)
            )
            await s.commit()
    return Response(status_code=204)
