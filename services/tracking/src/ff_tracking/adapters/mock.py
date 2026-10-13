"""Deterministic mock provider: a realistic timeline that progresses with time.

The timeline is a pure function of (reference, reference_type, anchor); ``now`` only decides how
many events have already happened. No randomness, no network.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta

from ff_tracking.domain.carriers import (
    carrier_for_awb_prefix,
    carrier_for_container_owner,
    find_carrier,
)
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.models import (
    CarrierRef,
    FlightRef,
    TrackingEvent,
    TrackingSnapshot,
    VesselRef,
)
from ff_tracking.domain.places import KnownPlace, place

_SEA_ORIGINS = ("CNSHA", "CNNGB", "CNYTN", "CNTAO", "CNXMN")
_SEA_DESTS = {"IQUQR": "IQBSR", "AEJEA": "AEDXB", "TRMER": "TRMERC"}
_AIR_ORIGINS = ("PVG", "CAN", "SZX")
_AIR_DESTS = {"BGW": "IQBGW", "EBL": "IQEBL", "BSR": "IQBSR"}
_VESSELS = ("Ever Given Star", "Maersk Sentosa", "MSC Aurora", "CMA CGM Marco Polo", "COSCO Pioneer")
_SEA_WAYPOINTS = ("south_china_sea", "singapore_strait", "malacca_strait", "indian_ocean", "arabian_sea", "hormuz")
_AIR_CARRIER_CODES = ("qatar_airways", "emirates", "turkish")


def _h(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def _km(a: KnownPlace, b: KnownPlace) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(d))


class MockProvider:
    id = "mock"

    async def track(
        self, reference: str, reference_type: ReferenceType, carrier: CarrierRef | None,
        *, anchor: datetime, now: datetime,
    ) -> TrackingSnapshot:
        h = _h(reference, reference_type.value)
        is_air = reference_type is ReferenceType.AWB
        origin_code = (_AIR_ORIGINS if is_air else _SEA_ORIGINS)[h % (3 if is_air else 5)]
        dests = _AIR_DESTS if is_air else _SEA_DESTS
        dest_code = list(dests)[(h >> 8) % len(dests)]
        origin, dest = place(origin_code), place(dest_code)
        final = place(dests[dest_code])
        start = anchor - timedelta(hours=1 + (h >> 16) % 240)  # registered some hours/days after booking
        carrier = carrier or self._detect(reference, reference_type, h)

        specs: list[tuple[S, timedelta, KnownPlace, str, str, str | None]] = []
        t = timedelta(0)

        def add(status: S, dt: timedelta, loc: KnownPlace, en: str, ar: str, sfx: str | None = None) -> None:
            nonlocal t
            t += dt
            specs.append((status, t, loc, en, ar, sfx))

        hours = timedelta(hours=1)
        if is_air:
            add(S.BOOKED, 0 * hours, origin, "Booking confirmed", "تم تأكيد الحجز")
            add(S.GATE_IN, 20 * hours, origin, "Cargo received at origin airport", "تم استلام الشحنة في مطار المغادرة")
            add(S.LOADED, 12 * hours, origin, "Loaded on aircraft", "تم التحميل على الطائرة")
            add(S.DEPARTED, 3 * hours, origin, "Flight departed", "أقلعت الرحلة")
            add(S.ARRIVED, (6 + (h >> 20) % 18) * hours, dest, "Flight arrived", "وصلت الرحلة")
            add(S.CUSTOMS_HOLD, 4 * hours, dest, "Customs inspection", "تفتيش جمركي")
            add(S.RELEASED, (10 + (h >> 24) % 20) * hours, dest, "Released by customs", "تم الإفراج الجمركي")
        else:
            sea_days = max(8.0, _km(origin, dest) * 1.35 / 620)
            add(S.BOOKED, 0 * hours, origin, "Booking confirmed", "تم تأكيد الحجز")
            add(S.GATE_IN, 36 * hours, origin, "Container gated in at terminal", "دخلت الحاوية المحطة")
            add(S.LOADED, 30 * hours, origin, "Loaded on vessel", "تم التحميل على السفينة")
            add(S.DEPARTED, 10 * hours, origin, "Vessel departed", "غادرت السفينة")
            legs = [place(w) for w in _SEA_WAYPOINTS]
            seg = timedelta(hours=sea_days * 24 / (len(legs) + 1))
            for i, wp in enumerate(legs):
                if i == 2 and h % 2 == 0:
                    add(S.TRANSSHIPMENT, seg, place("MYPKG"), "Transshipment at Port Klang", "إعادة شحن في بورت كلانغ")
                else:
                    add(S.IN_TRANSIT, seg, wp, "Vessel under way", "السفينة في الطريق")
            add(S.ARRIVED, seg, dest, "Vessel arrived at port", "وصلت السفينة إلى الميناء")
            add(S.DISCHARGED, 14 * hours, dest, "Container discharged", "تم تفريغ الحاوية")
            if h % 3 == 0:
                add(S.CUSTOMS_HOLD, 8 * hours, dest, "Customs hold", "حجز جمركي")
            add(S.RELEASED, (20 + (h >> 24) % 40) * hours, dest, "Released by customs", "تم الإفراج الجمركي")
        add(S.OUT_FOR_DELIVERY, 12 * hours, final, "Out for delivery", "في الطريق للتسليم")
        add(S.DELIVERED, (10 + (h >> 28) % 14) * hours, final, "Delivered", "تم التسليم")

        vessel = flight = None
        if is_air:
            code = carrier.iata_code if carrier and carrier.iata_code else "QR"
            flight = FlightRef(number=f"{code}{100 + h % 900}", carrier_code=code)
        else:
            imo = reference if reference_type is ReferenceType.VESSEL_IMO else None
            vessel = VesselRef(name=_VESSELS[(h >> 4) % len(_VESSELS)], imo=imo, voyage=f"{h % 90 + 10:02d}{'EW'[h % 2]}")

        events = []
        arrival_at = None
        for idx, (status, off, loc, en, ar, _) in enumerate(specs):
            ts = start + off
            if status is S.ARRIVED:
                arrival_at = ts
            if ts <= now:
                events.append(TrackingEvent(
                    id=f"evt_{h:016x}_{idx:02d}", status=status, description=en, description_ar=ar,
                    location=loc.event_location(), timestamp=ts, vessel=vessel, flight=flight, source=self.id,
                ))
        return TrackingSnapshot(
            provider=self.id, fetched_at=now, events=tuple(events), eta=arrival_at,
            origin=origin.location(), origin_hub_id=origin.code,
            destination=final.location(), destination_hub_id=dest.code,
            vessel=vessel, flight=flight, carrier=carrier,
        )

    @staticmethod
    def _detect(reference: str, reference_type: ReferenceType, h: int) -> CarrierRef | None:
        if reference_type is ReferenceType.CONTAINER and (c := carrier_for_container_owner(reference[:4])):
            return c.ref()
        if reference_type is ReferenceType.AWB and (c := carrier_for_awb_prefix(reference[:3])):
            return c.ref()
        if reference_type is ReferenceType.AWB and (c := find_carrier(_AIR_CARRIER_CODES[h % 3])):
            return c.ref()
        return None



