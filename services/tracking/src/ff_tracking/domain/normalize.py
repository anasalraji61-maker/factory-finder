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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.models import (
    EventLocation,
    FlightRef,
    GeoPoint,
    Location,
    TrackingEvent,
)
from ff_tracking.domain.places import find_place
from ff_tracking.domain.progress import PROGRESS
from ff_tracking.domain.validators import parse_vessel

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


MAX_TS_CHARS = 64


def parse_ts(value: Any) -> datetime | None:
    """ISO-8601 (any offset) or epoch seconds/ms -> aware UTC. Naive strings are taken as UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            v = float(value) / (1000 if value > 1e11 else 1)
            return datetime.fromtimestamp(v, UTC)
        text = str(value).strip()
        if len(text) > MAX_TS_CHARS:  # untrusted provider text; also keeps the suffix handling linear
            return None
        if text[-3:].upper() in ("UTC", "GMT"):  # (a regex ``\s*(?:UTC|GMT)$`` is quadratic on whitespace runs)
            text = text[:-3].rstrip() + "Z"
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
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
DEDUPE_WINDOW = timedelta(seconds=120)  # same status + place within this window = the same real-world event
CLOCK_SKEW = timedelta(minutes=15)  # an explicit actual event this far ahead of ``now`` is provider clock skew
_FLIGHT = re.compile(r"^([A-Z0-9]{2})\s*0*([0-9]{1,4}[A-Z]?)$")


def parse_flight(value: Any) -> FlightRef | None:
    """``"ek 306"`` / ``"EK0306"`` -> ``EK306``; anything that is not an IATA designator + number is dropped."""
    m = _FLIGHT.match(str(value or "").strip().upper())
    return FlightRef(number=m.group(1) + m.group(2), carrier_code=m.group(1)) if m else None


def _planned_rank(raw: Mapping[str, Any]) -> tuple:
    """Which planned arrival wins: an estimate (EST) beats a plan (PLN), then the most recently created."""
    est = 1 if str(raw.get("classifier") or "").upper().startswith("EST") else 0
    return est, parse_ts(raw.get("created")) or datetime.min.replace(tzinfo=UTC)


def normalize_events(
    raw_events: Iterable[Mapping[str, Any]], *, source: str, now: datetime,
    destination_hub: str | None = None, carrier_code: str | None = None,
) -> tuple[list[TrackingEvent], datetime | None, dict[str, datetime], int]:
    """Return ``(events, planned_arrival_eta, milestones, skipped_count)``.

    * unknown codes / unparsable timestamps are skipped (counted)
    * non-actual (planned) events never enter the timeline; a planned arrival **at the destination** (any
      planned arrival when the destination is unknown, the last one then) becomes the ETA; an estimate
      (``classifier`` EST) supersedes a plan (PLN), then the latest ``created``
    * an explicit ``actual: true`` event up to 15 minutes ahead of ``now`` is accepted (provider clock skew)
    * duplicates collapse: the same provider ``event_id`` (latest poll wins) or the same status + place within
      2 minutes; output is ordered by (time, progress)
    * a discharge/arrival at a hub other than the known destination becomes TRANSSHIPMENT
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    anon: list[Mapping[str, Any]] = []
    for raw in raw_events:
        if raw.get("event_id"):
            by_id[str(raw["event_id"])] = raw  # same event seen again in a later poll: the last copy wins
        else:
            anon.append(raw)
    kept: dict[tuple, list[TrackingEvent]] = {}
    gate_out: list[datetime] = []
    plans: list[tuple[tuple, datetime, str | None]] = []
    skipped = 0
    for raw in (*by_id.values(), *anon):
        code = norm_code(raw.get("code"))
        status = map_status(code, carrier_code)
        ts = parse_ts(raw.get("timestamp"))
        if status is None or ts is None:
            skipped += 1
            continue
        loc = resolve_location(raw.get("hub"), raw.get("name"), raw.get("country"), raw.get("lat"), raw.get("lon"))
        hub_id = loc.hub_id if loc else None
        future = ts > now and not (raw.get("actual") is True and ts <= now + CLOCK_SKEW)
        if raw.get("actual") is False or future:
            if status in (S.ARRIVED, S.DISCHARGED) and (not destination_hub or not hub_id or hub_id == destination_hub):
                plans.append((_planned_rank(raw), ts, hub_id))
            continue
        if status in (S.ARRIVED, S.DISCHARGED) and destination_hub and hub_id and hub_id != destination_hub:
            status = S.TRANSSHIPMENT
        if _GATE_OUT.match(code):
            gate_out.append(ts)
        place = hub_id or (loc.name if loc else "")
        if any(abs(e.timestamp - ts) <= DEDUPE_WINDOW for e in kept.get((status, place), ())):
            continue
        vessel = parse_vessel(raw.get("vessel"))
        flight = parse_flight(raw.get("flight"))
        desc = str(raw.get("description") or "").strip()[:300] or DESC_EN[status]
        kept.setdefault((status, place), []).append(TrackingEvent(
            id=_event_id(source, code, ts, hub_id or "", raw.get("event_id")), status=status,
            description=desc, description_ar=DESC_AR[status], location=loc, timestamp=ts,
            vessel=vessel, flight=flight, source=source))
    events = sorted((e for group in kept.values() for e in group),
                    key=lambda e: (e.timestamp, PROGRESS.get(e.status, 0), e.id))[-MAX_EVENTS:]
    milestones = detect_milestones(events, gate_out)
    eta = None
    if plans:
        best = max(rank for rank, _, _ in plans)
        at_best = [(ts, hub) for rank, ts, hub in plans if rank == best]
        eta = min(ts for ts, _ in at_best) if destination_hub else max(ts for ts, _ in at_best)
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
