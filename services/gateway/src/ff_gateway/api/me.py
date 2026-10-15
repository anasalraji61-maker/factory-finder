"""Profile endpoints and home feed."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ff_gateway.api.auth import _tokens, send_verification
from ff_gateway.api.deps import current_user, internal_headers, require_verified, to_me
from ff_gateway.db import RefreshToken, User
from ff_gateway.domain.errors import (
    AccountExists,
    RateLimited,
    ReauthFailed,
    SupplierClaimed,
    ValidationFailed,
)
from ff_gateway.domain.mail import Mail
from ff_gateway.domain.security import hash_password, verify_password
from ff_gateway.schemas import (
    ChangePasswordIn,
    MeOut,
    MePatch,
    TokensOut,
    check_password_policy,
)

router = APIRouter(tags=["me"])


async def _check_current_password(request: Request, user: User, password: str) -> None:
    """Re-auth with the current password; failures are throttled per user (a stolen access token cannot brute-force it)."""
    app = request.app
    limit = app.state.settings.login_fail_limit_per_minute
    key = f"pwfail:{user.id}"
    if limit > 0 and (wait := await app.state.limiter.blocked(key, limit)) is not None:
        raise RateLimited(wait, limit)
    if not verify_password(password, user.password_hash):
        if limit > 0:
            await app.state.limiter.check(key, limit)
        raise ReauthFailed("Current password is incorrect")


@router.post("/v1/me/password", response_model=TokensOut)
async def change_password(
    body: ChangePasswordIn, request: Request, user: User = Depends(current_user)
) -> TokensOut:
    """Change the password (re-auth with the current one). All refresh tokens are revoked; the response carries a fresh session for this device."""
    await _check_current_password(request, user, body.current_password)
    try:
        check_password_policy(body.new_password, user.email, user.phone)
        if body.new_password == body.current_password:
            raise ValueError("new password must differ from the current one")
    except ValueError as e:
        raise ValidationFailed.for_field("new_password", str(e)) from None
    now = request.app.state.clock.now()
    async with request.app.state.sessionmaker() as s:
        db_user = await s.get(User, user.id)
        assert db_user is not None
        db_user.password_hash = hash_password(body.new_password, request.app.state.settings.bcrypt_rounds)
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        await s.commit()
    return await _tokens(request, db_user, with_user=False)


@router.get("/v1/me", response_model=MeOut)
async def get_me(user: User = Depends(current_user)) -> MeOut:
    return to_me(user)


@router.patch("/v1/me", response_model=MeOut)
async def patch_me(body: MePatch, request: Request, user: User = Depends(current_user)) -> MeOut:
    data = body.model_dump(exclude_unset=True)
    current_password = data.pop("current_password", None)
    if "email" in data and data["email"] != user.email:  # changing (or removing) the login email needs re-auth
        if not current_password:
            raise ValidationFailed.for_field("current_password", "current_password is required to change email")
        await _check_current_password(request, user, current_password)
    if data.get("supplier_id") and data["supplier_id"] != user.supplier_id:
        require_verified(request, user)  # new supplier claim
    if "name" in data and data["name"] is None:
        raise ValidationFailed.for_field("name", "name cannot be null")
    for required in ("role", "display_currency", "language"):
        if required in data and data[required] is None:
            raise ValidationFailed.for_field(required, f"{required} cannot be null")
    async with request.app.state.sessionmaker() as s:
        db_user = await s.get(User, user.id)
        assert db_user is not None
        for field in ("email", "phone"):
            changed = bool(data.get(field)) and data[field] != getattr(db_user, field)
            if changed and await s.scalar(select(User).where(getattr(User, field) == data[field])):
                raise AccountExists(field)
        sid = data.get("supplier_id")
        if sid and sid != db_user.supplier_id:
            holder = await s.scalar(select(User).where(User.supplier_id == sid))
            if holder is not None and holder.id != db_user.id:
                raise SupplierClaimed()
        if (
            "email" in data and data["email"] is None and not (db_user.phone or data.get("phone"))
        ) or (
            "phone" in data and data["phone"] is None and not (db_user.email or data.get("email"))
        ):
            raise ValidationFailed.for_field(
                "email", "an account needs at least one of email or phone"
            )
        if "supplier_id" in data:
            if sid is None:  # release
                db_user.supplier_claim_status = "none"
            elif sid != db_user.supplier_id:  # new claim: never trusted until an admin approves it
                db_user.supplier_claim_status = "pending"
        email_changed = "email" in data and data["email"] != db_user.email
        old_email = db_user.email
        if email_changed:
            db_user.email_verified = False
        for k, v in data.items():
            setattr(
                db_user,
                k,
                body.default_destination.model_dump(exclude_none=True)
                if k == "default_destination" and v is not None
                else v,
            )
        try:
            await s.commit()
        except IntegrityError as e:
            await s.rollback()
            if sid:
                raise SupplierClaimed() from e
            raise AccountExists() from e
        if email_changed and old_email and request.app.state.mailer.enabled:  # tell the previous address
            await request.app.state.mailer.send(Mail(
                to=old_email, subject="Your email address was changed",
                body="The email address of your Factory Finder account was changed. If this was not you, reset your password now.\n",
            ))  # fmt: skip
        if email_changed and db_user.email:
            await send_verification(request, db_user)
        return to_me(db_user)


@router.get("/v1/home")
async def home(request: Request, user: User = Depends(current_user)) -> dict:
    dest = (user.default_destination or {}).get("country_code")
    feed = await request.app.state.home_client.fetch(
        display_currency=user.display_currency, destination_country=dest,
        headers=internal_headers(request, user.id),
    )  # fmt: skip
    return {"user": {"id": user.id, "name": user.name, "language": user.language}, **feed}
