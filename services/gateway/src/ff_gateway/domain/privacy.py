"""Account export and deletion: gateway profile + fan-out to every service that holds user data.

Deletion is soft-then-anonymize. ``request_deletion`` either schedules it (grace days > 0) or runs ``finalize`` at once:
the gateway row is scrubbed (id kept), refresh/verification tokens are removed and one durable ``DeletionJob`` per
service is stored. Jobs run immediately and are retried with backoff by the worker until done (or dead after
``deletion_max_attempts``). Logs and the audit table carry opaque ids and counters only, never PII.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from ff_gateway.db import AccountEvent, DeletionJob, EmailVerificationToken, RefreshToken, User
from ff_gateway.obs import LOGGER_NAME, configure_logging

log = logging.getLogger(LOGGER_NAME)

# Services that hold per-user data. Each implements POST .../export and DELETE .../data (contracts/openapi/<svc>.yaml).
PRIVACY_SERVICES: tuple[str, ...] = (
    "notifications", "messaging", "feed", "freight", "rfq", "media",
    "demand", "trust", "payments", "assistant", "sourcing", "tracking",
)  # fmt: skip
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600


def audit(app, event: str, user_id: str, request_id: str | None = None, detail: str | None = None) -> None:
    """Structured log line (no PII). The durable copy is written by ``record_event``."""
    configure_logging()
    log.info("audit", extra={"ff": {"event": "audit", "action": event, "user_id": user_id, "request_id": request_id, "detail": detail}})


async def record_event(app, user_id: str, event: str, request_id: str | None, detail: str | None = None) -> None:
    async with app.state.sessionmaker() as s:
        s.add(AccountEvent(user_id=user_id, event=event, detail=detail, request_id=request_id, created_at=app.state.clock.now()))
        await s.commit()
    audit(app, event, user_id, request_id, detail)


def _headers(app, request_id: str | None, supplier_id: str | None) -> dict[str, str]:
    h: dict[str, str] = {}
    if request_id:
        h["X-Request-Id"] = request_id
    if app.state.settings.internal_token:
        h["X-Internal-Token"] = app.state.settings.internal_token
    if supplier_id:
        h["X-Supplier-Id"] = supplier_id
    return h


def _url(app, service: str, user_id: str, suffix: str) -> str | None:
    base = app.state.settings.upstream_map().get(service)
    return f"{base.rstrip('/')}/v1/internal/users/{quote(user_id, safe='')}/{suffix}" if base else None


def verified_supplier(user: User) -> str | None:
    return user.supplier_id if user.supplier_id and user.supplier_claim_status == "verified" else None


# ------------------------------------------------------------------ export
async def _export_one(app, service: str, user: User, request_id: str | None) -> dict[str, Any]:
    st = app.state.settings
    url = _url(app, service, user.id, "export")
    if url is None:
        return {"status": "error", "error": "not_configured"}
    cap = st.export_max_bytes

    async def run() -> dict[str, Any]:
        async with app.state.http.stream(
            "POST", url, headers=_headers(app, request_id, verified_supplier(user) if service == "sourcing" else None),
            timeout=st.privacy_timeout_seconds
        ) as r:
            if r.status_code != 200:
                return {"status": "error", "error": f"http_{r.status_code}"}
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > cap:
                    return {"status": "error", "error": "too_large"}
        body = json.loads(bytes(buf))
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            return {"status": "error", "error": "bad_response"}
        return {"status": "ok", "truncated": bool(body.get("truncated")), "data": body["data"]}

    try:
        return await asyncio.wait_for(run(), timeout=st.privacy_timeout_seconds)
    except TimeoutError:
        return {"status": "error", "error": "timeout"}
    except (httpx.HTTPError, ValueError):
        return {"status": "error", "error": "unavailable"}


def profile_dict(u: User) -> dict[str, Any]:
    return {
        "id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "company": u.company, "role": u.role,
        "default_destination": u.default_destination, "supplier_id": u.supplier_id,
        "supplier_claim_status": u.supplier_claim_status, "email_verified": bool(u.email and u.email_verified),
        "display_currency": u.display_currency, "language": u.language,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }  # fmt: skip


async def build_export(app, user: User, request_id: str | None) -> dict[str, Any]:
    """Profile + every service's data. Failures are reported per service; the whole bundle stays under the size cap."""
    results = await asyncio.gather(*(_export_one(app, s, user, request_id) for s in PRIVACY_SERVICES))
    cap, total = app.state.settings.export_max_bytes, 0
    services: dict[str, Any] = {}
    for name, res in zip(PRIVACY_SERVICES, results, strict=True):
        if res["status"] == "ok":
            size = len(json.dumps(res["data"], separators=(",", ":"), default=str))
            if total + size > cap:
                res = {"status": "error", "error": "size_cap"}
            else:
                total += size
        services[name] = res
    return {
        "format_version": 1, "generated_at": app.state.clock.now().isoformat(), "user": profile_dict(user),
        "services": services, "partial": any(v["status"] != "ok" for v in services.values()),
    }  # fmt: skip


async def stream_export(bundle: dict[str, Any]) -> AsyncIterator[bytes]:
    """Emit the (already size-bounded) bundle piece by piece: header, then one service per chunk."""
    head = {k: v for k, v in bundle.items() if k != "services"}
    yield (json.dumps(head, ensure_ascii=False, default=str)[:-1] + ',"services":{').encode()
    for i, (name, res) in enumerate(bundle["services"].items()):
        yield ((",") if i else "").encode() + json.dumps({name: res}, ensure_ascii=False, default=str)[1:-1].encode()
    yield b"}}"


# ------------------------------------------------------------------ deletion
def _ensure_aware(d: datetime | None) -> datetime | None:
    from datetime import UTC

    return d if d is None or d.tzinfo else d.replace(tzinfo=UTC)


async def request_deletion(app, user_id: str, request_id: str | None) -> dict[str, Any]:
    """Idempotent. Returns the status body (see ``deletion_status``)."""
    now = app.state.clock.now()
    grace = app.state.settings.deletion_grace_days
    async with app.state.sessionmaker() as s:
        u = await s.get(User, user_id)
        if u is None:
            raise LookupError(user_id)
        already = u.deleted_at is not None or u.deletion_scheduled_at is not None
        if not already:
            u.is_active = False
            u.token_version = (u.token_version or 0) + 1  # access tokens die with the deactivation
            u.deletion_scheduled_at = now + timedelta(days=grace)
            await s.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))  # every session ends now
            await s.commit()
    drop_active_cache(app, user_id)
    if not already:
        await record_event(app, user_id, "deletion_requested", request_id, f"grace_days={grace}")
    if grace == 0:
        await finalize_deletion(app, user_id, request_id)
        await run_jobs(app, user_id=user_id, request_id=request_id)
    return await deletion_status(app, user_id)


def drop_active_cache(app, user_id: str) -> None:
    cache = app.state.__dict__.get("_active_cache")
    if cache is not None:
        cache.pop(user_id, None)


async def finalize_deletion(app, user_id: str, request_id: str | None = None) -> bool:
    """Anonymize the gateway row (keep the id) and queue the per-service jobs. Safe to repeat."""
    now = app.state.clock.now()
    async with app.state.sessionmaker() as s:
        u = await s.get(User, user_id)
        if u is None or u.deleted_at is not None:
            return False
        supplier = verified_supplier(u)
        u.email, u.phone, u.name, u.company = None, None, "Deleted user", None
        u.default_destination, u.supplier_id, u.supplier_claim_status = None, None, "none"
        u.password_hash = "!deleted:" + secrets.token_hex(8)  # never matches a bcrypt hash
        u.email_verified, u.is_active, u.deleted_at = False, False, now
        u.token_version = (u.token_version or 0) + 1
        await s.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await s.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id))
        for svc in PRIVACY_SERVICES:
            s.add(DeletionJob(
                user_id=user_id, service=svc, status="pending", attempts=0, next_attempt_at=now,
                supplier_id=supplier if svc == "sourcing" else None, created_at=now, updated_at=now,
            ))  # fmt: skip
        try:
            await s.commit()
        except IntegrityError:  # a concurrent finalize won
            await s.rollback()
            return False
    drop_active_cache(app, user_id)
    await record_event(app, user_id, "deletion_finalized", request_id, f"services={len(PRIVACY_SERVICES)}")
    return True


async def _call_erase(app, service: str, user_id: str, supplier_id: str | None, request_id: str | None) -> str | None:
    """One DELETE to a service. Returns None on success, else a short error code (never a response body)."""
    st = app.state.settings
    url = _url(app, service, user_id, "data")
    if url is None:
        return "not_configured"
    try:
        r = await asyncio.wait_for(
            app.state.http.request("DELETE", url, headers=_headers(app, request_id, supplier_id), timeout=st.privacy_timeout_seconds),
            timeout=st.privacy_timeout_seconds,
        )
    except TimeoutError:
        return "timeout"
    except httpx.HTTPError:
        return "unavailable"
    if r.status_code != 200:
        return f"http_{r.status_code}"
    try:
        body = r.json()
    except ValueError:
        return "bad_response"
    return None if isinstance(body, dict) and body.get("status") == "done" else "bad_response"


async def run_jobs(app, user_id: str | None = None, request_id: str | None = None, limit: int = 200) -> int:
    """Run every due pending job (optionally one user's): HTTP calls in parallel, results written back serially.
    Returns how many were attempted."""
    st, now = app.state.settings, app.state.clock.now()
    q = select(DeletionJob).where(DeletionJob.status == "pending", DeletionJob.next_attempt_at <= now)
    if user_id:
        q = q.where(DeletionJob.user_id == user_id)
    async with app.state.sessionmaker() as s:
        todo = [(j.id, j.user_id, j.service, j.supplier_id) for j in (await s.scalars(q.order_by(DeletionJob.id).limit(limit))).all()]
    errors = await asyncio.gather(*(_call_erase(app, svc, uid, sup, request_id) for _, uid, svc, sup in todo))
    now = app.state.clock.now()
    finished: dict[str, list[str]] = {}  # user -> dead services
    async with app.state.sessionmaker() as s:
        for (job_id, uid, svc, _), err in zip(todo, errors, strict=True):
            job = await s.get(DeletionJob, job_id)
            if job is None:
                continue
            job.attempts += 1
            job.updated_at, job.last_error = now, err
            if err is None:
                job.status, job.supplier_id = "done", None
            elif job.attempts >= st.deletion_max_attempts:
                job.status = "dead"
                finished.setdefault(uid, []).append(svc)
            else:
                job.next_attempt_at = now + timedelta(seconds=min(BACKOFF_BASE_SECONDS * 2 ** (job.attempts - 1), BACKOFF_MAX_SECONDS))
        await s.commit()
    for uid in {u for _, u, _, _ in todo}:
        async with app.state.sessionmaker() as s:
            left = await s.scalar(select(func.count()).select_from(DeletionJob).where(DeletionJob.user_id == uid, DeletionJob.status != "done"))
        if finished.get(uid):
            await record_event(app, uid, "job_dead", request_id, "services=" + ",".join(sorted(finished[uid])))
        if not left:
            await record_event(app, uid, "deletion_completed", request_id, f"services={len(PRIVACY_SERVICES)}")
    return len(todo)


async def process_due(app) -> dict[str, int]:
    """Worker tick: finalize accounts whose grace period is over, then run due jobs."""
    now = app.state.clock.now()
    async with app.state.sessionmaker() as s:
        due = list((await s.scalars(
            select(User.id).where(User.deleted_at.is_(None), User.deletion_scheduled_at.is_not(None), User.deletion_scheduled_at <= now).limit(100)
        )).all())  # fmt: skip
    for uid in due:
        await finalize_deletion(app, uid)
    return {"finalized": len(due), "jobs": await run_jobs(app)}


async def deletion_status(app, user_id: str) -> dict[str, Any]:
    async with app.state.sessionmaker() as s:
        u = await s.get(User, user_id)
        jobs = list((await s.scalars(select(DeletionJob).where(DeletionJob.user_id == user_id))).all())
    assert u is not None
    services = {j.service: {"done": "done", "pending": "pending", "dead": "failed"}[j.status] for j in jobs}
    if u.deleted_at is None:
        status = "scheduled"
    else:
        status = "deleted" if all(v == "done" for v in services.values()) else "partial"
    return {
        "status": status,
        "scheduled_for": (_ensure_aware(u.deletion_scheduled_at).isoformat() if u.deletion_scheduled_at and u.deleted_at is None else None),
        "deleted_at": _ensure_aware(u.deleted_at).isoformat() if u.deleted_at else None,
        "services": services,
    }  # fmt: skip


async def cancel_deletion(app, user_id: str) -> bool:
    """Grace-period cancel (used by login with the right password). False if already finalized."""
    async with app.state.sessionmaker() as s:
        res = await s.execute(
            update(User).where(User.id == user_id, User.deleted_at.is_(None), User.deletion_scheduled_at.is_not(None))
            .values(deletion_scheduled_at=None, is_active=True)
        )  # fmt: skip
        await s.commit()
    drop_active_cache(app, user_id)
    if res.rowcount:
        await record_event(app, user_id, "deletion_cancelled", None)
    return bool(res.rowcount)
