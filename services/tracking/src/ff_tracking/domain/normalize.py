"""Provider events -> our event model.

Input is a provider-neutral "raw event" dict (each adapter converts its own wire shape to it):
``code, description?, timestamp, hub?, name?, country?, lat?, lon?, vessel?, flight?, event_id?, actual?``.
All mapping tables below are UNVERIFIED against any live provider; fixtures drive the tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.models import (
    EventLocation,
    FlightRef,
    GeoPoint,
    Location,
    TrackingEvent,
    VesselRef,
)
from ff_tracking.domain.places import find_place
from ff_tracking.domain.progress import PROGRESS

_STATUS_FILE = Path(__file__).resolve().parent.parent / "data" / "status_map.json"


def _load_status_tables() -> tuple[dict[str, S], dict[str, dict[str, S]]]:
    raw = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    default = {k: S(v) for k, v in raw["default"].items()}
    per_carrier = {c: {k: S(v) for k, v in table.items()} for c, table in raw.get("carriers", {}).items()}
    return default, per_carrier


# Provider status code (upper snake) -> normalized status, data driven (data/status_map.json). Ocean aggregator
# codes and IATA Cargo-IMP (air) codes live in the default table; they do not collide. Carrier tables override it.
STATUS_MAP, CARRIER_STATUS_MAPS = _load_status_tables()


def map_status(code: Any, carrier_code: str | None = None) -> S | None:
    """Normalized status for a provider code (carrier table first, then the default table, then the generic DCSA profile); ``None`` = unknown."""
    key = norm_code(code)
    if carrier_code and (hit := CARRIER_STATUS_MAPS.get(carrier_code, {}).get(key)) is not None:
        return hit
    return STATUS_MAP.get(key) or CARRIER_STATUS_MAPS.get("dcsa", {}).get(key)


def resolve_status(code: Any, carrier_code: str | None = None, current: S | None = None) -> S:
    """Status after applying one provider code to a shipment currently in ``current``.

    Unknown codes never move the shipment (``current``, or ``booked`` when nothing is known yet) and a delivered
    shipment is never reopened by a different status."""
    mapped = map_status(code, carrier_code)
    if current is S.DELIVERED:
        return S.DELIVERED
    if mapped is None:
        return current or S.BOOKED
    return mapped


_GATE_OUT = re.compile(r"^(FULL_)?GATE_OUT(_FULL)?$")
_LOCODE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")
_IATA = re.compile(r"^[A-Z]{3}$")

DESC_AR: dict[S, str] = {
    S.BOOKED: "تم تأكيد الحجز", S.GATE_IN: "دخول المحطة", S.LOADED: "تم التحميل",
    S.DEPARTED: "المغادرة", S.IN_TRANSIT: "في الطريق", S.TRANSSHIPMENT: "إعادة شحن",
    S.ARRIVED: "الوصول", S.DISCHARGED: "تم التفريغ", S.CUSTOMS_HOLD: "حجز جمركي",
    S.RELEASED: "تم الإفراج الجمركي", S.OUT_FOR_DELIVERY: "في الطريق للتسليم / خروج من المحطة",
    S.DELIVERED: "تم التسليم", S.EXCEPTION: "استثناء / تأخير",
}
DESC_EN: dict[S, str] = {s: s.value.replace("_", " ").capitalize() for s in S}


def norm_code(code: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(code or "").upper()).strip("_")


def parse_ts(value: Any) -> datetime | None:
    """ISO-8601 (any offset) or epoch seconds/ms -> aware UTC. Naive strings are taken as UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            v = float(value) / (1000 if value > 1e11 else 1)
            return datetime.fromtimestamp(v, UTC)
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def resolve_location(hub: Any = None, name: Any = None, country: Any = None,
                     lat: Any = None, lon: Any = None) -> EventLocation | None:
    """UN/LOCODE or IATA -> known place; otherwise a best-effort location (country from LOCODE)."""
    code = str(hub or "").strip().upper().replace(" ", "")
    if (known := find_place(code)) is not None:
        return known.event_location()
    cc = str(country or "").strip().upper()
    cc = cc if re.fullmatch(r"[A-Z]{2}", cc) else None
    hub_id = None
    if _LOCODE.fullmatch(code):
        hub_id, cc = code, cc or code[:2]
    elif _IATA.fullmatch(code):
        hub_id = code
    label = str(name).strip() if name else (code or None)
    if not label:
        return None
    point = None
    try:
        if lat is not None and lon is not None:
            point = GeoPoint(lat=float(lat), lon=float(lon))
    except (ValueError, TypeError):
        point = None
    return EventLocation(name=label, country_code=cc, hub_id=hub_id, point=point)


def location_of(hub: Any, country: Any = None) -> Location | None:
    """Coarse origin/destination (needs a country): known place, LOCODE prefix or explicit country."""
    code = str(hub or "").strip().upper()
    if (known := find_place(code)) is not None and known.country_code:
        return known.location()
    cc = str(country or (code[:2] if _LOCODE.fullmatch(code) else "")).upper()
    return Location(country_code=cc) if re.fullmatch(r"[A-Z]{2}", cc) else None


def _event_id(source: str, code: str, ts: datetime, hub: str, raw_id: Any) -> str:
    if raw_id:
        return f"evt_{hashlib.sha256(f'{source}|{raw_id}'.encode()).hexdigest()[:20]}"
    return "evt_" + hashlib.sha256(f"{source}|{code}|{ts.isoformat()}|{hub}".encode()).hexdigest()[:20]


MAX_EVENTS = 300  # a provider cannot grow the stored aggregate without bound


def normalize_events(
    raw_events: Iterable[Mapping[str, Any]], *, source: str, now: datetime,
    destination_hub: str | None = None, carrier_code: str | None = None,
) -> tuple[list[TrackingEvent], datetime | None, dict[str, datetime], int]:
    """Return ``(events, planned_arrival_eta, milestones, skipped_count)``.

    * unknown codes / unparsable timestamps are skipped (counted)
    * non-actual (planned) events never enter the timeline; a planned arrival becomes the ETA
    * duplicates (same status, hub, minute) collapse; output is ordered by (time, progress)
    * a discharge/arrival at a hub other than the known destination becomes TRANSSHIPMENT
    """
    seen: dict[tuple, TrackingEvent] = {}
    gate_out: list[datetime] = []
    eta: datetime | None = None
    skipped = 0
    for raw in raw_events:
        code = norm_code(raw.get("code"))
        status = map_status(code, carrier_code)
        ts = parse_ts(raw.get("timestamp"))
        if status is None or ts is None:
            skipped += 1
            continue
        if raw.get("actual") is False or ts > now:
            if status in (S.ARRIVED, S.DISCHARGED) and (eta is None or ts < eta):
                eta = ts
            continue
        loc = resolve_location(raw.get("hub"), raw.get("name"), raw.get("country"), raw.get("lat"), raw.get("lon"))
        hub_id = loc.hub_id if loc else None
        if status in (S.ARRIVED, S.DISCHARGED) and destination_hub and hub_id and hub_id != destination_hub:
            status = S.TRANSSHIPMENT
        if _GATE_OUT.match(code):
            gate_out.append(ts)
        key = (status, hub_id or (loc.name if loc else ""), ts.replace(second=0, microsecond=0))
        if key in seen:
            continue
        v, f = raw.get("vessel"), raw.get("flight")
        vessel = VesselRef(name=str(v["name"]), imo=v.get("imo") or None, voyage=v.get("voyage")) \
            if isinstance(v, Mapping) and v.get("name") else None
        flight = FlightRef(number=str(f), carrier_code=str(f)[:2]) if isinstance(f, str) and f else None
        desc = str(raw.get("description") or "").strip()[:300] or DESC_EN[status]
        seen[key] = TrackingEvent(
            id=_event_id(source, code, ts, hub_id or "", raw.get("event_id")), status=status,
            description=desc, description_ar=DESC_AR[status], location=loc, timestamp=ts,
            vessel=vessel, flight=flight, source=source)
    events = sorted(seen.values(), key=lambda e: (e.timestamp, PROGRESS[e.status], e.id))[-MAX_EVENTS:]
    milestones = detect_milestones(events, gate_out)
    return events, eta, milestones, skipped


def detect_milestones(events: list[TrackingEvent], gate_out: list[datetime] | None = None) -> dict[str, datetime]:
    """First time each milestone happened: gate_in, loaded, departed, transshipment, arrived,
    discharged, gate_out, delivered."""
    m: dict[str, datetime] = {}
    for e in events:
        m.setdefault(e.status.value, e.timestamp)
    keep = ("gate_in", "loaded", "departed", "transshipment", "arrived", "discharged", "delivered")
    out = {k: m[k] for k in keep if k in m}
    if gate_out:
        out["gate_out"] = min(gate_out)
    return out
