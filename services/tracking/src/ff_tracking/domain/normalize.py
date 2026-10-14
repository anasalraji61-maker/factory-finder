"""Provider events -> our event model.

Input is a provider-neutral "raw event" dict (each adapter converts its own wire shape to it):
``code, description?, timestamp, hub?, name?, country?, lat?, lon?, vessel?, flight?, event_id?, actual?``.
All mapping tables below are UNVERIFIED against any live provider; fixtures drive the tests.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
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

# Provider status code (upper snake) -> normalized status. Ocean aggregator codes and IATA
# Cargo-IMP (air) codes live in one table; they do not collide.
STATUS_MAP: dict[str, S] = {
    # ocean
    "BOOKED": S.BOOKED, "BOOKING_CONFIRMED": S.BOOKED, "EMPTY_GATE_OUT": S.BOOKED,
    "GATE_OUT_EMPTY": S.BOOKED, "EMPTY_PICKUP": S.BOOKED,
    "GATE_IN": S.GATE_IN, "GATE_IN_FULL": S.GATE_IN, "FULL_GATE_IN": S.GATE_IN,
    "LOADED": S.LOADED, "LOAD": S.LOADED, "LOADED_ON_VESSEL": S.LOADED, "LOADED_ON_BOARD": S.LOADED,
    "DEPARTED": S.DEPARTED, "DEPARTURE": S.DEPARTED, "VESSEL_DEPARTURE": S.DEPARTED, "VESSEL_DEPARTED": S.DEPARTED,
    "IN_TRANSIT": S.IN_TRANSIT, "UNDER_WAY": S.IN_TRANSIT,
    "TRANSSHIPMENT": S.TRANSSHIPMENT, "TRANSSHIPMENT_DISCHARGE": S.TRANSSHIPMENT,
    "TRANSSHIPMENT_LOAD": S.TRANSSHIPMENT, "TS_DISCHARGE": S.TRANSSHIPMENT, "TS_LOAD": S.TRANSSHIPMENT,
    "ARRIVED": S.ARRIVED, "ARRIVAL": S.ARRIVED, "VESSEL_ARRIVAL": S.ARRIVED, "VESSEL_ARRIVED": S.ARRIVED,
    "DISCHARGED": S.DISCHARGED, "DISCHARGE": S.DISCHARGED, "UNLOADED": S.DISCHARGED,
    "CUSTOMS_HOLD": S.CUSTOMS_HOLD, "CUSTOMS_INSPECTION": S.CUSTOMS_HOLD, "HOLD": S.CUSTOMS_HOLD,
    "RELEASED": S.RELEASED, "CUSTOMS_RELEASED": S.RELEASED, "CUSTOMS_CLEARED": S.RELEASED,
    # gate-out of the full container is the "gate_out" milestone; status-wise it leaves the terminal
    "GATE_OUT": S.OUT_FOR_DELIVERY, "GATE_OUT_FULL": S.OUT_FOR_DELIVERY, "FULL_GATE_OUT": S.OUT_FOR_DELIVERY,
    "OUT_FOR_DELIVERY": S.OUT_FOR_DELIVERY,
    "DELIVERED": S.DELIVERED, "EMPTY_RETURNED": S.DELIVERED, "EMPTY_RETURN": S.DELIVERED,
    "EXCEPTION": S.EXCEPTION, "DELAYED": S.EXCEPTION, "DAMAGED": S.EXCEPTION,
    # air (IATA Cargo-IMP status codes)
    "BKD": S.BOOKED, "RCS": S.GATE_IN, "MAN": S.LOADED, "DEP": S.DEPARTED, "TFD": S.TRANSSHIPMENT,
    "RCT": S.TRANSSHIPMENT, "ARR": S.ARRIVED, "RCF": S.DISCHARGED, "AWD": S.CUSTOMS_HOLD,
    "CCD": S.RELEASED, "NFD": S.RELEASED, "DLV": S.DELIVERED, "DIS": S.EXCEPTION,
}
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


def normalize_events(
    raw_events: Iterable[Mapping[str, Any]], *, source: str, now: datetime,
    destination_hub: str | None = None,
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
        status = STATUS_MAP.get(code)
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
        desc = str(raw.get("description") or "").strip() or DESC_EN[status]
        seen[key] = TrackingEvent(
            id=_event_id(source, code, ts, hub_id or "", raw.get("event_id")), status=status,
            description=desc, description_ar=DESC_AR[status], location=loc, timestamp=ts,
            vessel=vessel, flight=flight, source=source)
    events = sorted(seen.values(), key=lambda e: (e.timestamp, PROGRESS[e.status], e.id))
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
