"""Tracking change events -> alert drafts (pure). Consumer side of tracking's outbox rows.

An event is one ``tracking_outbox`` row: ``dedupe_key`` (unique), ``shipment_id``, ``owner_id``,
``kind`` (status_changed | shipment_delayed) and a ``payload`` (status, previous_status, eta, label,
reference, delayed, delay_hours, ...). Unknown statuses fall back to generic text, not an error.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from ff_notifications.domain.messages import clip
from ff_notifications.domain.models import AlertMessage, AlertPayload, RuleKind

KINDS = {"status_changed": RuleKind.SHIPMENT_STATUS, "shipment_delayed": RuleKind.SHIPMENT_DELAYED}
_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

STATUS_TEXT: dict[str, tuple[str, str]] = {
    "booked": ("booked", "تم الحجز"),
    "picked_up": ("picked up", "تم الاستلام من المورد"),
    "in_transit": ("in transit", "في الطريق"),
    "departed": ("departed", "غادرت الشحنة"),
    "arrived": ("arrived", "وصلت الشحنة"),
    "at_port": ("at port", "في الميناء"),
    "customs": ("in customs clearance", "قيد التخليص الجمركي"),
    "customs_cleared": ("customs cleared", "تم التخليص الجمركي"),
    "out_for_delivery": ("out for delivery", "خرجت للتسليم"),
    "delivered": ("delivered", "تم التسليم"),
    "exception": ("has an exception", "حدثت مشكلة"),
    "delayed": ("delayed", "متأخرة"),
}


class InvalidEvent(ValueError):
    """Event rejected: the message is safe to echo back to the (internal) caller."""


@dataclass(frozen=True, slots=True)
class TrackingEvent:
    dedupe_key: str
    owner_id: str
    shipment_id: str
    kind: str
    payload: dict[str, Any]

    @property
    def rule(self) -> RuleKind:
        return KINDS[self.kind]

    @property
    def watch_id(self) -> str:
        """Alerts of one shipment share a pseudo watch id (fits ``alerts.watch_id``, 40 chars)."""
        return "shp_" + hashlib.sha256(self.shipment_id.encode()).hexdigest()[:24]


def parse_event(raw: dict[str, Any]) -> TrackingEvent:
    key = raw.get("dedupe_key")
    if not isinstance(key, str) or not 1 <= len(key) <= 300:
        raise InvalidEvent("dedupe_key is required (<= 300 chars)")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise InvalidEvent(f"unsupported kind (expected one of {', '.join(KINDS)})")
    owner, ship = raw.get("owner_id"), raw.get("shipment_id")
    if not isinstance(owner, str) or not _ID.match(owner):
        raise InvalidEvent("owner_id is required")
    if not isinstance(ship, str) or not 1 <= len(ship) <= 128:
        raise InvalidEvent("shipment_id is required")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise InvalidEvent("payload must be an object")
    return TrackingEvent(key, owner, ship, kind, payload)


def _txt(v: Any, limit: int) -> str | None:
    return (
        clip(" ".join(str(v).split()), limit)
        if isinstance(v, str | int | float) and str(v).strip()
        else None
    )


def status_texts(status: str | None) -> tuple[str, str]:
    if not status:
        return "updated", "تم التحديث"
    known = STATUS_TEXT.get(status.strip().lower())
    if known:
        return known
    human = clip(status.replace("_", " ").strip(), 40)
    return human, human  # unknown code: shown as-is in both languages


def _name(p: dict[str, Any]) -> str:
    return _txt(p.get("label"), 60) or _txt(p.get("reference"), 40) or "shipment"


def build(event: TrackingEvent) -> tuple[AlertMessage, AlertPayload]:
    p = event.payload
    name = _name(p)
    status = _txt(p.get("status"), 40)
    en, ar = status_texts(status)
    eta = _txt(p.get("eta"), 40)
    if event.rule is RuleKind.SHIPMENT_DELAYED:
        hours = p.get("delay_hours")
        h = (
            f"{round(float(hours))}"
            if isinstance(hours, int | float) and not isinstance(hours, bool) and hours > 0
            else None
        )
        body = (
            f"Shipment {name} is delayed"
            + (f" by about {h} h" if h else "")
            + (f"; new ETA {eta}" if eta else "")
            + "."
        )
        body_ar = (
            f"الشحنة {name} متأخرة"
            + (f" بحدود {h} ساعة" if h else "")
            + (f"؛ الموعد المتوقع الجديد {eta}" if eta else "")
            + "."
        )
        msg = AlertMessage("Shipment delayed", "تأخر في الشحنة", body, body_ar)
    else:
        body = f"Shipment {name}: {en}" + (f" (ETA {eta})" if eta else "") + "."
        body_ar = f"الشحنة {name}: {ar}" + (f" (الوصول المتوقع {eta})" if eta else "") + "."
        msg = AlertMessage("Shipment update", "تحديث الشحنة", body, body_ar)
    shipment = {"shipment_id": event.shipment_id, "kind": event.kind}
    for k, lim in (
        ("reference", 64),
        ("reference_type", 32),
        ("label", 60),
        ("status", 40),
        ("previous_status", 40),
        ("eta", 40),
    ):
        if (v := _txt(p.get(k), lim)) is not None:
            shipment[k] = v
    if isinstance(p.get("delayed"), bool):
        shipment["delayed"] = p["delayed"]
    if isinstance(p.get("delay_hours"), int | float) and not isinstance(p.get("delay_hours"), bool):
        shipment["delay_hours"] = p["delay_hours"]
    return msg, AlertPayload(listing_ids=(), shipment=shipment)
