"""Listing events (public, anonymous allowed) and the supplier's own analytics (/v1/my/analytics)."""

from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict

from ..analytics import Analytics
from .errors import ApiError
from .my import Supplier

router = APIRouter()
_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}\Z")
_USER_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}\Z")


def normalise_ip(raw: str) -> str:
    """Canonical viewer key: IPv4 as is, IPv4-mapped IPv6 -> IPv4, other IPv6 -> its /64 (one subscriber owns a whole /64, so
    rotating addresses inside it must not dodge the per-viewer rate limit / dedupe). Non-IP text is kept (internal callers only)."""
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return raw.strip()[:64]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


class EventIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["view", "contact_click", "share"]


@router.post("/v1/listings/{listing_id}/events", status_code=202)
async def post_event(
    listing_id: str,
    body: EventIn,
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
    x_client_ip: Annotated[str | None, Header()] = None,
) -> dict:
    if not _ID_RE.match(listing_id):
        raise ApiError(422, "invalid_listing_id", "Invalid listing id")
    a: Analytics = request.app.state.analytics
    ip = normalise_ip((x_client_ip or (request.client.host if request.client else "") or "unknown")[:100])
    uid = (x_user_id or "").strip()
    uid = uid if _USER_RE.match(uid) else None
    # only published native listings are countable; everything else answers the same 202 (nothing is revealed)
    countable = listing_id.startswith("nat_") and await request.app.state.native.store.get_published(listing_id) is not None
    return {"counted": await a.record_event(listing_id, body.type, ip, uid, countable)}


@router.get("/v1/my/analytics")
async def my_analytics(
    request: Request,
    sup: Supplier,
    days: Annotated[int, Query()] = 30,
    listing_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    if days not in (7, 30, 90):
        raise ApiError(422, "invalid_days", "days must be 7, 30 or 90")
    owned = await request.app.state.native.store.owned_summaries(sup)
    if listing_id is not None:
        owned = [o for o in owned if o[0] == listing_id]
        if not owned:  # also other suppliers' ids: never reveal existence
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
    a: Analytics = request.app.state.analytics
    return await a.overview(owned, days)
