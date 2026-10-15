"""Register / login / refresh."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import and_, delete, select, update
from sqlalchemy.exc import IntegrityError

from ff_gateway.api.deps import current_user, request_ip_key, to_me
from ff_gateway.db import (
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    User,
    bump_token_version,
)
from ff_gateway.domain import privacy
from ff_gateway.domain.errors import (
    AccountDisabled,
    AccountExists,
    InvalidCredentials,
    InvalidResetToken,
    InvalidToken,
    InvalidVerificationToken,
    RateLimited,
    ValidationFailed,
)
from ff_gateway.domain.mail import Mail
from ff_gateway.domain.security import hash_jti, hash_password, verify_password
from ff_gateway.schemas import (
    ForgotPasswordIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    ResendVerificationIn,
    ResetPasswordIn,
    TokensOut,
    VerifyEmailIn,
    check_password_policy,
)

log = logging.getLogger("ff_gateway")
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
        access_token=t.access(user.id, user.token_version or 0), refresh_token=refresh, expires_in=t.access_ttl,
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
    conds = []  # both given -> both must match the same account (never an OR that lets one identifier ride along)
    if body.email:
        conds.append(User.email == body.email)
    if body.phone:
        conds.append(User.phone == body.phone)
    # per-account throttle (on top of the per-IP limit): a botnet guessing one account's password is slowed down; keyed on a
    # hash of the identifier so it is also applied to unknown accounts (no enumeration) and holds no PII
    app = request.app
    fkeys = ["loginfail:" + hashlib.sha256(i.encode()).hexdigest()[:32] for i in (body.email, body.phone) if i]
    fail_limit = app.state.settings.login_fail_limit_per_minute
    if fail_limit > 0:
        for fkey in fkeys:  # every identifier supplied has its own bucket: pairing a victim's phone with random emails does not dodge it
            if (wait := await app.state.limiter.blocked(fkey, fail_limit)) is not None:
                raise RateLimited(wait, fail_limit)
    async with request.app.state.sessionmaker() as s:
        user = await s.scalar(select(User).where(and_(*conds)))
    # always run a bcrypt check so unknown accounts are not distinguishable by response time
    ok = (
        verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        and user is not None
    )
    if not ok or user is None:
        if fail_limit > 0:
            for fkey in fkeys:
                await app.state.limiter.check(fkey, fail_limit)
        raise InvalidCredentials()
    if not user.is_active:
        # grace period after DELETE /v1/me: the right password cancels the deletion (never for admin-disabled or finalized accounts)
        if user.deletion_scheduled_at is None or user.deleted_at is not None or not await privacy.cancel_deletion(request.app, user.id):
            raise AccountDisabled()
        user.is_active = True
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


async def send_password_reset(request: Request, user: User) -> None:
    """Issue a fresh single-use reset token (older ones are dropped) and mail it. No-op when mail is off."""
    app = request.app
    mailer = app.state.mailer
    if not (mailer.enabled and user.email):
        return
    st = app.state.settings
    token = secrets.token_urlsafe(32)
    now = app.state.clock.now()
    async with app.state.sessionmaker() as s:
        await s.execute(
            delete(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id)
            .execution_options(synchronize_session=False)
        )
        s.add(PasswordResetToken(
            token_hash=_hash_token(token), user_id=user.id,
            expires_at=now + timedelta(seconds=st.password_reset_ttl_seconds),
        ))  # fmt: skip
        await s.commit()
    link = st.password_reset_url_template.format(token=token) if st.password_reset_url_template else None
    minutes = max(1, st.password_reset_ttl_seconds // 60)
    body = (
        f"Someone asked to reset the password of your Factory Finder account. The code works once and expires in {minutes} minutes.\n\n"
        + (f"Open: {link}\n" if link else f"Reset code: {token}\n")
        + "\nIf this was not you, ignore this email; your password is unchanged."
    )
    await mailer.send(Mail(to=user.email, subject="Reset your password", body=body))


async def _forgot_task(request: Request, email: str) -> None:
    """Runs after the 202 has been sent: the account lookup must not shape the response time."""
    try:
        async with request.app.state.sessionmaker() as s:
            user = await s.scalar(select(User).where(User.email == email))
        if user is not None and user.is_active and user.deleted_at is None:
            await send_password_reset(request, user)
    except Exception:
        log.warning("password reset mail failed", exc_info=False)


@router.post("/password/forgot", status_code=202)
async def password_forgot(body: ForgotPasswordIn, request: Request, tasks: BackgroundTasks) -> dict:
    """Always 202 with the same body: no account enumeration. Throttled silently per email+IP and per email."""
    app = request.app
    st = app.state.settings
    h = hashlib.sha256(body.email.encode()).hexdigest()[:32]
    ip = request_ip_key(request)
    lim = app.state.limiter
    over_pair = await lim.check(f"pwforgot:{h}:{ip}", max(st.password_forgot_per_minute, 1)) is not None
    over_email = await lim.check(f"pwforgot-e:{h}", max(st.password_forgot_per_email_per_minute, 1)) is not None
    if not (over_pair or over_email):
        tasks.add_task(_forgot_task, request, body.email)
    return {"status": "accepted"}


@router.post("/password/reset", status_code=204)
async def password_reset(body: ResetPasswordIn, request: Request) -> Response:
    """Consume a reset token (single use, 30 min) and set a new password; every refresh token of the user is revoked."""
    app = request.app
    now = app.state.clock.now()
    key = _hash_token(body.token)
    async with app.state.sessionmaker() as s:
        row = await s.get(PasswordResetToken, key)
        if row is None or row.used_at is not None or _aware(row.expires_at) <= now:
            raise InvalidResetToken()
        user = await s.get(User, row.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise InvalidResetToken()
        try:
            check_password_policy(body.new_password, user.email, user.phone)
        except ValueError as e:  # token stays usable: the user just picks a better password
            raise ValidationFailed.for_field("new_password", str(e)) from None
        res = await s.execute(  # atomic single use
            update(PasswordResetToken)
            .where(PasswordResetToken.token_hash == key, PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 0:
            raise InvalidResetToken()
        user.password_hash = hash_password(body.new_password, app.state.settings.bcrypt_rounds)
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        await s.execute(
            delete(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.token_hash != key)
            .execution_options(synchronize_session=False)
        )
        await bump_token_version(s, user.id)  # access tokens issued before the reset stop working
        await s.commit()
    privacy.drop_active_cache(app, user.id)
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
async def logout_all(request: Request, user: User = Depends(current_user)) -> Response:
    """Sign out everywhere: every refresh token of the user is revoked and every access token issued so far (this one
    included) stops working."""
    app = request.app
    async with app.state.sessionmaker() as s:
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=app.state.clock.now())
            .execution_options(synchronize_session=False)
        )
        await bump_token_version(s, user.id)
        await s.commit()
    privacy.drop_active_cache(app, user.id)
    return Response(status_code=204)
