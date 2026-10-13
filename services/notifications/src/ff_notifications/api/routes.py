"""Thin FastAPI routes."""

from __future__ import annotations

import hmac
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ff_notifications.domain.models import Alert, Device, Locale, Platform, SearchQuery, Watch
from ff_notifications.domain.money import Money, MoneyError
from ff_notifications.errors import Invalid, Unauthenticated
from ff_notifications.service import NotificationService

router = APIRouter(prefix="/v1")


def svc(request: Request) -> NotificationService:
    return request.app.state.service


def _check_token(request: Request, token: str | None) -> None:
    expected = request.app.state.settings.internal_token_value
    if expected is not None and not hmac.compare_digest(token or "", expected):
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
async def list_watchlist(user: User, s: Service) -> dict[str, Any]:
    items = await s.list_watches(user)
    return {"items": [watch_json(w) for w in items], "total": len(items)}


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
