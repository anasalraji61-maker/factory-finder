"""Domain objects <-> JSON documents / timestamps."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ff_notifications.domain.delivery import Delivery, DeliveryStatus, Prefs, QuietHours
from ff_notifications.domain.models import (
    STATE_FIELDS,
    Alert,
    AlertMessage,
    AlertPayload,
    Device,
    Locale,
    Platform,
    RuleKind,
    SearchQuery,
    Watch,
    WatchType,
)
from ff_notifications.domain.money import Money, format_amount, parse_amount
from ff_notifications.domain.verification import Verification

_MONEY_FIELDS = {"baseline_price", "current_price", "equivalent_price"}
_TS_FIELDS = {"last_checked_at", "baseline_at"}


def ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def watch_to_doc(w: Watch) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "owner_id": w.owner_id,
        "type": w.type.value,
        "drop_threshold_pct": format_amount(w.drop_threshold_pct),
        "created_at": ts(w.created_at),
        "updated_at": ts(w.updated_at),
        "listing_id": w.listing_id,
        "search": w.search.to_json() if w.search else None,
        "target_price": w.target_price.to_json() if w.target_price else None,
        "active": w.active,
        "version": w.version,
    }
    for name in STATE_FIELDS:
        value = getattr(w, name)
        if name in _MONEY_FIELDS:
            value = value.to_json() if value else None
        elif name in _TS_FIELDS:
            value = ts(value) if value else None
        elif name == "seen_listing_ids":
            value = list(value) if value is not None else None
        doc[name] = value
    return doc


def watch_from_row(row: Mapping[str, Any]) -> Watch:
    d = dict(row["doc"])
    kwargs: dict[str, Any] = {}
    for name in STATE_FIELDS:
        value = d.get(name)
        if name in _MONEY_FIELDS:
            value = Money.from_json(value) if value else None
        elif name in _TS_FIELDS:
            value = parse_ts(value) if value else None
        elif name == "seen_listing_ids":
            value = tuple(value) if value is not None else None
        kwargs[name] = value
    return Watch(
        id=row["id"],
        owner_id=d["owner_id"],
        type=WatchType(d["type"]),
        drop_threshold_pct=parse_amount(d["drop_threshold_pct"]),
        created_at=parse_ts(d["created_at"]),
        updated_at=parse_ts(d["updated_at"]),
        listing_id=d.get("listing_id"),
        search=SearchQuery.from_json(d["search"]) if d.get("search") else None,
        target_price=Money.from_json(d["target_price"]) if d.get("target_price") else None,
        active=bool(d.get("active", True)),
        version=int(d.get("version", 1)),
        **kwargs,
    )


def alert_to_doc(a: Alert) -> dict[str, Any]:
    return {
        "owner_id": a.owner_id,
        "watch_id": a.watch_id,
        "rule": a.rule.value,
        "fingerprint": a.fingerprint,
        "message": {
            "title": a.message.title,
            "title_ar": a.message.title_ar,
            "body": a.message.body,
            "body_ar": a.message.body_ar,
        },
        "payload": a.payload.to_json(),
        "created_at": ts(a.created_at),
        "read": a.read,
        "read_at": ts(a.read_at) if a.read_at else None,
    }


def alert_from_row(row: Mapping[str, Any]) -> Alert:
    d = row["doc"]
    return Alert(
        id=row["id"],
        owner_id=d["owner_id"],
        watch_id=d["watch_id"],
        rule=RuleKind(d["rule"]),
        message=AlertMessage(**d["message"]),
        payload=AlertPayload.from_json(d["payload"]),
        fingerprint=d["fingerprint"],
        created_at=parse_ts(d["created_at"]),
        read=bool(row["read"]),
        read_at=parse_ts(d["read_at"]) if d.get("read_at") else None,
    )


def device_to_doc(dv: Device) -> dict[str, Any]:
    return {
        "owner_id": dv.owner_id,
        "platform": dv.platform.value,
        "locale": dv.locale.value,
        "token": dv.token,
        "created_at": ts(dv.created_at),
        "updated_at": ts(dv.updated_at),
        "active": dv.active,
    }


def device_from_row(row: Mapping[str, Any]) -> Device:
    d = row["doc"]
    return Device(
        id=row["id"],
        owner_id=d["owner_id"],
        platform=Platform(d["platform"]),
        locale=Locale(d["locale"]),
        token=d["token"],
        created_at=parse_ts(d["created_at"]),
        updated_at=parse_ts(d["updated_at"]),
        active=bool(d.get("active", True)),
    )


def prefs_to_doc(p: Prefs) -> dict[str, Any]:
    return {
        "channels": {k: list(v) for k, v in p.channels.items()},
        "quiet_hours": {"start": p.quiet_hours.start, "end": p.quiet_hours.end}
        if p.quiet_hours
        else None,
        "timezone": p.timezone,
        "language": p.language.value if p.language else None,
        "digest_email": p.digest_email,
        "digest_email_pending": p.digest_email_pending,
    }


def prefs_from_row(row: Mapping[str, Any]) -> Prefs:
    d = row["doc"]
    qh = d.get("quiet_hours")
    return Prefs(
        owner_id=row["owner_id"],
        channels={k: tuple(v) for k, v in d["channels"].items()},
        quiet_hours=QuietHours(qh["start"], qh["end"]) if qh else None,
        timezone=d["timezone"],
        language=Locale(d["language"]) if d.get("language") else None,
        # legacy docs stored an unverified "email": deliberately ignored (never verified)
        digest_email=d.get("digest_email"),
        digest_email_pending=d.get("digest_email_pending"),
        explicit=True,
    )


def delivery_to_doc(dl: Delivery) -> dict[str, Any]:
    return {
        "channel": dl.channel,
        "kind": dl.kind,
        "alert_ids": list(dl.alert_ids),
        "device_id": dl.device_id,
        "attempts": dl.attempts,
        "last_error": dl.last_error,
        "created_at": ts(dl.created_at),
        "updated_at": ts(dl.updated_at) if dl.updated_at else None,
    }


def delivery_from_row(row: Mapping[str, Any]) -> Delivery:
    d = row["doc"]
    return Delivery(
        id=row["id"],
        owner_id=row["owner_id"],
        channel=d["channel"],
        kind=d["kind"],
        alert_ids=tuple(d["alert_ids"]),
        created_at=parse_ts(d["created_at"]),
        next_attempt_at=parse_ts(row["next_attempt_at"]),
        device_id=d.get("device_id"),
        status=DeliveryStatus(row["status"]),
        attempts=d["attempts"],
        last_error=d.get("last_error"),
        updated_at=parse_ts(d["updated_at"]) if d.get("updated_at") else None,
    )


def verification_to_doc(v: Verification) -> dict[str, Any]:
    return {
        "email": v.email,
        "salt": v.salt,
        "code_hash": v.code_hash,
        "expires_at": ts(v.expires_at) if v.expires_at else None,
        "attempts": v.attempts,
        "locked_until": ts(v.locked_until) if v.locked_until else None,
        "sends": [ts(t) for t in v.sends],
    }


def verification_from_row(row: Mapping[str, Any]) -> Verification:
    d = row["doc"]
    return Verification(
        owner_id=row["owner_id"],
        email=d.get("email"),
        salt=d.get("salt", ""),
        code_hash=d.get("code_hash", ""),
        expires_at=parse_ts(d["expires_at"]) if d.get("expires_at") else None,
        attempts=int(d.get("attempts", 0)),
        locked_until=parse_ts(d["locked_until"]) if d.get("locked_until") else None,
        sends=tuple(parse_ts(t) for t in d.get("sends", [])),
    )
