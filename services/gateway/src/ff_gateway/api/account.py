"""Store-mandated account controls: in-app deletion (DELETE /v1/me) and privacy data export (GET /v1/me/export)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ff_gateway.api.deps import check_token_version, current_user, current_user_id
from ff_gateway.db import RefreshToken, User
from ff_gateway.domain import privacy
from ff_gateway.domain.errors import AccountDisabled, InvalidToken, RateLimited, ReauthFailed
from ff_gateway.domain.security import hash_jti, verify_password
from ff_gateway.schemas import DeleteAccountIn

router = APIRouter(tags=["account"])


async def account_user(request: Request) -> User:
    """Like ``current_user`` but lets an account that is being deleted (scheduled / done) through, so DELETE is idempotent."""
    uid = current_user_id(request)
    async with request.app.state.sessionmaker() as s:
        user = await s.get(User, uid)
    if user is None:
        raise InvalidToken("Token refers to an unknown user")
    if not user.is_active and user.deleted_at is None and user.deletion_scheduled_at is None:
        raise AccountDisabled()
    if user.is_active:  # a scheduled/finished deletion bumped the version itself; repeating DELETE must stay possible
        check_token_version(request, user)
    return user


async def _throttle(request: Request, user_id: str) -> None:
    limit = request.app.state.settings.privacy_rate_limit_per_minute
    if limit > 0 and (wait := await request.app.state.limiter.check(f"privacy:{user_id}", limit)) is not None:
        raise RateLimited(wait, limit)


async def _reauth(request: Request, user: User, body: DeleteAccountIn) -> None:
    if body.password:
        if verify_password(body.password, user.password_hash):
            return
    elif body.refresh_token:
        try:
            c = request.app.state.tokens.decode_refresh(body.refresh_token)
        except InvalidToken:
            raise ReauthFailed() from None
        async with request.app.state.sessionmaker() as s:
            row = await s.get(RefreshToken, hash_jti(c.jti))
        if row is not None and row.user_id == user.id == c.user_id and row.revoked_at is None and row.used_at is None:
            return
    raise ReauthFailed()


@router.delete("/v1/me")
async def delete_me(body: DeleteAccountIn, request: Request, user: User = Depends(account_user)) -> JSONResponse:
    """Delete the caller's account. Re-auth with the current password or refresh token. Idempotent: repeating it reports
    status and retries pending service cleanups (the first call is the only one that needs valid proof)."""
    app, rid = request.app, getattr(request.state, "request_id", None)
    await _throttle(request, user.id)
    if user.deleted_at is None and user.deletion_scheduled_at is None:
        try:
            await _reauth(request, user, body)
        except ReauthFailed:
            await privacy.record_event(app, user.id, "deletion_reauth_failed", rid)
            raise
    out = await privacy.request_deletion(app, user.id, rid)
    if out["status"] == "partial":
        await privacy.run_jobs(app, user_id=user.id, request_id=rid)  # a repeat call retries immediately
        out = await privacy.deletion_status(app, user.id)
    return JSONResponse(out, status_code=200 if out["status"] == "deleted" else 202)


@router.get("/v1/me/export")
async def export_me(request: Request, user: User = Depends(current_user)) -> StreamingResponse:
    """Privacy export: JSON bundle with the profile and what each service holds. Failures are reported per service."""
    app, rid = request.app, getattr(request.state, "request_id", None)
    await _throttle(request, user.id)
    bundle = await privacy.build_export(app, user, rid)
    failed = sorted(k for k, v in bundle["services"].items() if v["status"] != "ok")
    await privacy.record_event(app, user.id, "export_requested", rid, f"failed={len(failed)}")
    return StreamingResponse(
        privacy.stream_export(bundle), media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="factory-finder-export.json"', "Cache-Control": "no-store"},
    )
