"""Register / login / refresh."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from ff_gateway.api.deps import to_me
from ff_gateway.db import EmailVerificationToken, RefreshToken, User
from ff_gateway.domain.errors import (
    AccountDisabled,
    AccountExists,
    InvalidCredentials,
    InvalidToken,
    InvalidVerificationToken,
)
from ff_gateway.domain.mail import Mail
from ff_gateway.domain.security import hash_jti, hash_password, verify_password
from ff_gateway.schemas import (
    LoginIn,
    RefreshIn,
    RegisterIn,
    ResendVerificationIn,
    TokensOut,
    VerifyEmailIn,
)

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


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def send_verification(request: Request, user: User) -> None:
    """Issue a fresh single-use token (older unused ones are dropped) and mail it. No-op when mail is off."""
    app = request.app
    mailer = app.state.mailer
    if not (mailer.enabled and user.email):
        return
    st = app.state.settings
    token = secrets.token_urlsafe(32)
    now = app.state.clock.now()
    async with app.state.sessionmaker() as s:
        await s.execute(
            delete(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .execution_options(synchronize_session=False)
        )
        s.add(EmailVerificationToken(
            token_hash=_hash_token(token), user_id=user.id, email=user.email,
            expires_at=now + timedelta(seconds=st.email_verification_ttl_seconds),
        ))  # fmt: skip
        await s.commit()
    link = st.verify_url_template.format(token=token) if st.verify_url_template else None
    body = "Confirm your email address for Factory Finder.\n\n" + (
        f"Open: {link}\n" if link else f"Verification code: {token}\n"
    )
    await mailer.send(Mail(to=user.email, subject="Verify your email", body=body))


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
    await send_verification(request, user)
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


@router.post("/verify-email", status_code=204)
async def verify_email(body: VerifyEmailIn, request: Request) -> Response:
    """Consume a verification token. Unknown, expired, used or stale (email changed) -> one generic 400."""
    now = request.app.state.clock.now()
    key = _hash_token(body.token)
    async with request.app.state.sessionmaker() as s:
        row = await s.get(EmailVerificationToken, key)
        if row is None or row.used_at is not None or _aware(row.expires_at) <= now:
            raise InvalidVerificationToken()
        user = await s.get(User, row.user_id)
        if user is None or not user.is_active or user.email != row.email:
            raise InvalidVerificationToken()
        res = await s.execute(  # atomic single use
            update(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == key, EmailVerificationToken.used_at.is_(None))
            .values(used_at=now)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 0:
            raise InvalidVerificationToken()
        user.email_verified = True
        await s.commit()
    return Response(status_code=204)


@router.post("/resend-verification", status_code=202)
async def resend_verification(body: ResendVerificationIn, request: Request, tasks: BackgroundTasks) -> dict:
    """Always 202 with the same body: no account / verified-state enumeration. Throttled per address."""
    app = request.app
    key = "resend:" + hashlib.sha256(body.email.encode()).hexdigest()[:32]
    if await app.state.limiter.check(key, app.state.settings.resend_verification_per_minute) is None:
        async with app.state.sessionmaker() as s:
            user = await s.scalar(select(User).where(User.email == body.email))
        if user is not None and user.is_active and not user.email_verified:
            tasks.add_task(send_verification, request, user)  # after the response: no timing oracle
    return {"status": "accepted"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
