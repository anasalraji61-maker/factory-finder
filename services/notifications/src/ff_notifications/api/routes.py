"""Thin FastAPI routes."""

from __future__ import annotations

import hmac
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ff_notifications.domain.delivery import Prefs
from ff_notifications.domain.models import Alert, Device, Locale, Platform, SearchQuery, Watch
from ff_notifications.domain.money import Money, MoneyError
from ff_notifications.domain.verification import mask_email
from ff_notifications.errors import Invalid, NotFound, Unauthenticated
from ff_notifications.service import NotificationService

router = APIRouter(prefix="/v1")


def svc(request: Request) -> NotificationService:
    return request.app.state.service


def _check_token(request: Request, token: str | None) -> None:
    expected = request.app.state.settings.internal_token_value
    if expected is not None and not hmac.compare_digest((token or "").encode(), expected.encode()):
        raise Unauthenticated("Invalid internal token")


def current_user(
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> str:
    _check_token(request, x_internal_token)
    if not x_user_id or len(x_user_id) > 64:
        raise Unauthenticated("X-User-Id header is required")
    return x_user_id


def internal_only(
    request: Request, x_internal_token: Annotated[str | None, Header()] = None
) -> None:
    _check_token(request, x_internal_token)


def privacy_guard(
    request: Request, x_internal_token: Annotated[str | None, Header()] = None
) -> None:
    """Account export/erasure: internal token only; anything else looks like a missing route."""
    expected = request.app.state.settings.internal_token_value
    if expected is not None and not hmac.compare_digest(
        (x_internal_token or "").encode(), expected.encode()
    ):
        raise NotFound("Route not found")


User = Annotated[str, Depends(current_user)]
Service = Annotated[NotificationService, Depends(svc)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyIn(_Body):
    amount: str
    currency: str


class SearchIn(_Body):
    q: str | None = Field(default=None, max_length=200)
    kind: str | None = None
    condition: str | None = None
    origin_country: str | None = None
    category: str | None = None
    min_price: str | None = None
    max_price: str | None = None
    moq_max: int | None = Field(default=None, ge=0)
    verified_only: bool | None = None


class WatchCreate(_Body):
    listing_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_:\-][A-Za-z0-9_.:\-]*$"
    )
    search: SearchIn | None = None
    target_price: MoneyIn | None = None
    drop_threshold_pct: str | None = None


class DeviceCreate(_Body):
    platform: Platform
    token: str = Field(min_length=8, max_length=512)
    locale: Locale = Locale.AR


class QuietHoursIn(_Body):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class PrefsIn(_Body):
    channels: dict[str, list[str]] | None = None
    quiet_hours: QuietHoursIn | None = None
    clear_quiet_hours: bool = False
    timezone: str | None = Field(default=None, max_length=64)
    language: Locale | None = None
    digest_email: str | None = Field(default=None, max_length=254)
    email: str | None = Field(default=None, max_length=254)  # deprecated alias of digest_email


class VerifyEmailIn(_Body):
    code: str = Field(pattern=r"^\d{6}$")


class EvaluateIn(_Body):
    owner_id: str | None = None
    watch_id: str | None = None


def _money(m: Money | None) -> dict | None:
    return m.to_json() if m else None


def watch_json(w: Watch) -> dict[str, Any]:
    ts = lambda v: v.isoformat(timespec="milliseconds").replace("+00:00", "Z") if v else None  # noqa: E731
    return {
        "id": w.id,
        "type": w.type.value,
        "listing_id": w.listing_id,
        "search": w.search.to_json() if w.search else None,
        "target_price": _money(w.target_price),
        "drop_threshold_pct": str(w.drop_threshold_pct),
        "active": w.active,
        "created_at": ts(w.created_at),
        "updated_at": ts(w.updated_at),
        "title": w.title,
        "title_ar": w.title_ar,
        "baseline_price": _money(w.baseline_price),
        "current_price": _money(w.current_price),
        "available": w.available,
        "result_count": w.result_count,
        "last_checked_at": ts(w.last_checked_at),
    }


def alert_json(a: Alert) -> dict[str, Any]:
    ts = lambda v: v.isoformat(timespec="milliseconds").replace("+00:00", "Z") if v else None  # noqa: E731
    return {
        "id": a.id,
        "watch_id": a.watch_id,
        "rule": a.rule.value,
        "title": a.message.title,
        "title_ar": a.message.title_ar,
        "body": a.message.body,
        "body_ar": a.message.body_ar,
        "payload": a.payload.to_json(),
        "read": a.read,
        "created_at": ts(a.created_at),
        "read_at": ts(a.read_at),
    }


def device_json(d: Device) -> dict[str, Any]:
    return {
        "id": d.id,
        "platform": d.platform.value,
        "locale": d.locale.value,
        "token": d.token,
        "active": d.active,
        "created_at": d.created_at.isoformat().replace("+00:00", "Z"),
    }


@router.post("/watchlist", status_code=201)
async def add_watch(
    body: WatchCreate, user: User, s: Service, response: Response
) -> dict[str, Any]:
    try:
        search = (
            SearchQuery.from_json(body.search.model_dump(exclude_none=True))
            if body.search
            else None
        )
        target = (
            Money.of(body.target_price.amount, body.target_price.currency)
            if body.target_price
            else None
        )
        pct = Decimal(body.drop_threshold_pct) if body.drop_threshold_pct else None
    except (MoneyError, ArithmeticError, ValueError) as exc:
        raise Invalid(f"Invalid number or currency: {exc}", code="invalid_money") from exc
    watch, created = await s.add_watch(
        user, listing_id=body.listing_id, search=search, target_price=target, drop_threshold_pct=pct
    )
    if not created:
        response.status_code = 200
    return watch_json(watch)


@router.get("/watchlist")
async def list_watchlist(
    user: User, s: Service, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    items = await s.list_watches(user, limit=limit, offset=offset)
    return {"items": [watch_json(w) for w in items], "total": await s.count_watches(user)}


@router.delete("/watchlist/{watch_id}", status_code=204)
async def delete_watch(watch_id: str, user: User, s: Service) -> Response:
    await s.delete_watch(user, watch_id)
    return Response(status_code=204)


@router.get("/alerts")
async def list_alerts(
    user: User,
    s: Service,
    unread_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    items, total, unread, size = await s.list_alerts(
        user, unread_only=unread_only, page=page, page_size=page_size
    )
    return {
        "items": [alert_json(a) for a in items],
        "total": total,
        "page": page,
        "page_size": size,
        "unread_total": unread,
    }


@router.post("/alerts/evaluate", dependencies=[Depends(internal_only)])
async def evaluate_alerts(s: Service, body: EvaluateIn | None = None) -> dict[str, Any]:
    body = body or EvaluateIn()
    report = await s.evaluate_all(owner_id=body.owner_id, watch_id=body.watch_id)
    return {
        "evaluated": report.evaluated,
        "alerts_created": report.alerts_created,
        "pushes_sent": report.pushes_sent,
        "skipped": report.skipped,
        "errors": report.errors,
        "alerts": [alert_json(a) for a in report.alerts],
    }


class TrackingEventsIn(_Body):
    events: list[dict[str, Any]] = Field(min_length=1, max_length=100)


@router.post("/internal/tracking-events", dependencies=[Depends(internal_only)])
async def ingest_tracking_events(body: TrackingEventsIn, s: Service) -> dict[str, Any]:
    return await s.ingest_tracking_events(body.events)


@router.post("/alerts/read-all")
async def read_all(user: User, s: Service) -> dict[str, int]:
    return {"marked": await s.mark_all_read(user)}


@router.post("/alerts/{alert_id}/read")
async def read_alert(alert_id: str, user: User, s: Service) -> dict[str, Any]:
    return alert_json(await s.mark_read(user, alert_id))


@router.post("/devices", status_code=201)
async def register_device(
    body: DeviceCreate, user: User, s: Service, response: Response
) -> dict[str, Any]:
    device, created = await s.register_device(user, body.platform, body.token, body.locale)
    if not created:
        response.status_code = 200
    return device_json(device)


@router.get("/devices")
async def list_devices(user: User, s: Service) -> dict[str, Any]:
    return {"items": [device_json(d) for d in await s.store.list_devices(user)]}


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(device_id: str, user: User, s: Service) -> Response:
    await s.delete_device(user, device_id)
    return Response(status_code=204)


def prefs_json(p: Prefs) -> dict[str, Any]:
    return {
        "channels": {k: list(v) for k, v in p.channels.items()},
        "quiet_hours": {"start": p.quiet_hours.start, "end": p.quiet_hours.end}
        if p.quiet_hours
        else None,
        "timezone": p.timezone,
        "language": p.language.value if p.language else None,
        "digest_email": p.digest_email,
        "digest_email_verified": p.digest_email is not None,
        "digest_email_pending": mask_email(p.digest_email_pending),
        "email": p.digest_email,  # deprecated: the VERIFIED address only
    }


@router.get("/notification-prefs")
async def get_prefs(user: User, s: Service) -> dict[str, Any]:
    return prefs_json(await s.get_prefs(user))


@router.put("/notification-prefs")
async def put_prefs(body: PrefsIn, user: User, s: Service) -> dict[str, Any]:
    qh = (
        {}
        if body.clear_quiet_hours
        else (body.quiet_hours.model_dump() if body.quiet_hours else None)
    )
    prefs = await s.put_prefs(
        user,
        channels=body.channels,
        quiet_hours=qh,
        timezone=body.timezone,
        language=body.language,
        digest_email=body.digest_email if body.digest_email is not None else body.email,
    )
    return prefs_json(prefs)


@router.post("/notification-prefs/verify-email")
async def verify_email(body: VerifyEmailIn, user: User, s: Service) -> dict[str, Any]:
    return prefs_json(await s.verify_digest_email(user, body.code))


@router.post("/notification-prefs/resend-code")
async def resend_code(user: User, s: Service) -> dict[str, Any]:
    return prefs_json(await s.resend_digest_code(user))


@router.post("/alerts/digest", dependencies=[Depends(internal_only)])
async def send_digests(s: Service) -> dict[str, int]:
    return {"sent": await s.send_digests()}


@router.post("/internal/users/{user_id}/export", dependencies=[Depends(privacy_guard)])
async def export_user(user_id: str, s: Service) -> dict[str, Any]:
    return {"service": "notifications", "user_id": user_id, "truncated": False,
            "data": await s.store.export_owner(user_id)}  # fmt: skip


@router.delete("/internal/users/{user_id}/data", dependencies=[Depends(privacy_guard)])
async def erase_user(user_id: str, s: Service) -> dict[str, Any]:
    return {"service": "notifications", "user_id": user_id, "status": "done",
            "counts": await s.store.erase_owner(user_id)}  # fmt: skip
