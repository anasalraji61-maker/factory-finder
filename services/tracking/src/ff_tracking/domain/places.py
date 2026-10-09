"""Known places used to label tracking events (ports, airports, cities, sea areas).

Codes: UN/LOCODE for sea ports and cities, IATA for airports, a slug for sea areas.
Arabic names are used for the bilingual event descriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ff_tracking.domain.models import EventLocation, GeoPoint, Location


class PlaceKind(StrEnum):
    SEA_PORT = "sea_port"
    AIRPORT = "airport"
    CITY = "city"
    SEA_AREA = "sea_area"


@dataclass(frozen=True, slots=True)
class KnownPlace:
    code: str
    name: str
    name_ar: str
    kind: PlaceKind
    lat: float
    lon: float
    country_code: str | None = None
    city: str | None = None

    @property
    def point(self) -> GeoPoint:
        return GeoPoint(lat=self.lat, lon=self.lon)

    @property
    def is_hub(self) -> bool:
        return self.kind in (PlaceKind.SEA_PORT, PlaceKind.AIRPORT)

    def event_location(self) -> EventLocation:
        return EventLocation(
            name=self.name,
            name_ar=self.name_ar,
            country_code=self.country_code,
            hub_id=self.code if self.is_hub else None,
            point=self.point,
        )

    def location(self) -> Location:
        if self.country_code is None:
            raise ValueError(f"place {self.code} has no country")
        return Location(country_code=self.country_code, city=self.city or self.name, point=self.point)


_P = PlaceKind

_PLACES: tuple[KnownPlace, ...] = (
    # --- sea ports (UN/LOCODE) ---
    KnownPlace("CNSHA", "Shanghai", "شنغهاي", _P.SEA_PORT, 30.6262, 122.0650, "CN", "Shanghai"),
    KnownPlace("CNNGB", "Ningbo", "نينغبو", _P.SEA_PORT, 29.9360, 121.8450, "CN", "Ningbo"),
    KnownPlace("CNYTN", "Shenzhen (Yantian)", "شنتشن (يانتيان)", _P.SEA_PORT, 22.5740, 114.2780, "CN", "Shenzhen"),
    KnownPlace("CNTAO", "Qingdao", "تشينغداو", _P.SEA_PORT, 36.0110, 120.2010, "CN", "Qingdao"),
    KnownPlace("CNXMN", "Xiamen", "شيامن", _P.SEA_PORT, 24.4800, 118.0700, "CN", "Xiamen"),
    KnownPlace("MYPKG", "Port Klang", "بورت كلانغ", _P.SEA_PORT, 2.9990, 101.3920, "MY", "Port Klang"),
    KnownPlace("AEJEA", "Jebel Ali", "جبل علي", _P.SEA_PORT, 25.0110, 55.0610, "AE", "Dubai"),
    KnownPlace("IQUQR", "Umm Qasr", "أم قصر", _P.SEA_PORT, 30.0340, 47.9460, "IQ", "Umm Qasr"),
    KnownPlace("TRMER", "Mersin", "مرسين", _P.SEA_PORT, 36.7950, 34.6400, "TR", "Mersin"),
    # --- cities (UN/LOCODE) ---
    KnownPlace("IQBSR", "Basra", "البصرة", _P.CITY, 30.5085, 47.7804, "IQ", "Basra"),
    KnownPlace("IQBGW", "Baghdad", "بغداد", _P.CITY, 33.3152, 44.3661, "IQ", "Baghdad"),
    KnownPlace("IQEBL", "Erbil", "أربيل", _P.CITY, 36.1911, 44.0092, "IQ", "Erbil"),
    KnownPlace("AEDXB", "Dubai", "دبي", _P.CITY, 25.2048, 55.2708, "AE", "Dubai"),
    KnownPlace("AEAUH", "Abu Dhabi", "أبوظبي", _P.CITY, 24.4539, 54.3773, "AE", "Abu Dhabi"),
    KnownPlace("TRMERC", "Mersin", "مرسين", _P.CITY, 36.8121, 34.6415, "TR", "Mersin"),
    KnownPlace("TRGZT", "Gaziantep", "غازي عنتاب", _P.CITY, 37.0662, 37.3833, "TR", "Gaziantep"),
    KnownPlace("TRADA", "Adana", "أضنة", _P.CITY, 37.0000, 35.3213, "TR", "Adana"),
    # --- airports (IATA) ---
    KnownPlace("PVG", "Shanghai Pudong (PVG)", "مطار شنغهاي بودونغ", _P.AIRPORT, 31.1443, 121.8083, "CN", "Shanghai"),
    KnownPlace("CAN", "Guangzhou Baiyun (CAN)", "مطار قوانغتشو بايون", _P.AIRPORT, 23.3924, 113.2988, "CN", "Guangzhou"),
    KnownPlace("SZX", "Shenzhen Bao'an (SZX)", "مطار شنتشن باوآن", _P.AIRPORT, 22.6393, 113.8107, "CN", "Shenzhen"),
    KnownPlace("DXB", "Dubai International (DXB)", "مطار دبي الدولي", _P.AIRPORT, 25.2532, 55.3657, "AE", "Dubai"),
    KnownPlace("DOH", "Hamad International, Doha (DOH)", "مطار حمد الدولي في الدوحة", _P.AIRPORT, 25.2731, 51.6081, "QA", "Doha"),
    KnownPlace("IST", "Istanbul Airport (IST)", "مطار إسطنبول", _P.AIRPORT, 41.2753, 28.7519, "TR", "Istanbul"),
    KnownPlace("AUH", "Zayed International, Abu Dhabi (AUH)", "مطار زايد الدولي في أبوظبي", _P.AIRPORT, 24.4330, 54.6511, "AE", "Abu Dhabi"),
    KnownPlace("AMM", "Queen Alia International, Amman (AMM)", "مطار الملكة علياء الدولي في عمّان", _P.AIRPORT, 31.7226, 35.9932, "JO", "Amman"),
    KnownPlace("BGW", "Baghdad International (BGW)", "مطار بغداد الدولي", _P.AIRPORT, 33.2625, 44.2346, "IQ", "Baghdad"),
    KnownPlace("EBL", "Erbil International (EBL)", "مطار أربيل الدولي", _P.AIRPORT, 36.2376, 43.9632, "IQ", "Erbil"),
    KnownPlace("BSR", "Basra International (BSR)", "مطار البصرة الدولي", _P.AIRPORT, 30.5491, 47.6621, "IQ", "Basra"),
    # --- sea areas (positions reported while under way) ---
    KnownPlace("taiwan_strait", "Taiwan Strait", "مضيق تايوان", _P.SEA_AREA, 24.30, 119.50),
    KnownPlace("south_china_sea", "South China Sea", "بحر الصين الجنوبي", _P.SEA_AREA, 14.50, 112.50),
    KnownPlace("singapore_strait", "Singapore Strait", "مضيق سنغافورة", _P.SEA_AREA, 1.20, 103.90),
    KnownPlace("malacca_strait", "Strait of Malacca", "مضيق ملقا", _P.SEA_AREA, 4.80, 99.20),
    KnownPlace("indian_ocean", "Indian Ocean", "المحيط الهندي", _P.SEA_AREA, 6.00, 78.00),
    KnownPlace("arabian_sea", "Arabian Sea", "بحر العرب", _P.SEA_AREA, 16.00, 62.00),
    KnownPlace("hormuz", "Strait of Hormuz", "مضيق هرمز", _P.SEA_AREA, 26.40, 56.50),
    KnownPlace("arabian_gulf", "Arabian Gulf", "الخليج العربي", _P.SEA_AREA, 27.80, 50.60),
    KnownPlace("gulf_of_aden", "Gulf of Aden", "خليج عدن", _P.SEA_AREA, 12.40, 46.50),
    KnownPlace("red_sea", "Red Sea", "البحر الأحمر", _P.SEA_AREA, 20.00, 38.80),
    KnownPlace("suez_canal", "Suez Canal", "قناة السويس", _P.SEA_AREA, 30.60, 32.33),
    KnownPlace("east_med", "Eastern Mediterranean", "شرق البحر المتوسط", _P.SEA_AREA, 34.30, 33.20),
)

PLACES: dict[str, KnownPlace] = {p.code: p for p in _PLACES}


def place(code: str) -> KnownPlace:
    """Return a known place by code; raises KeyError for unknown codes (programming error)."""
    return PLACES[code]


def find_place(code: str | None) -> KnownPlace | None:
    """Lenient lookup used when labelling provider data (UN/LOCODE or IATA, any case)."""
    if not code:
        return None
    return PLACES.get(code.strip().upper()) or PLACES.get(code.strip())
