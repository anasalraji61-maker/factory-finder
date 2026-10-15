from typing import Literal

from pydantic import BaseModel, Field

HubType = Literal["sea", "air", "rail", "land_border", "consolidation"]


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Country(BaseModel):
    iso2: str = Field(pattern=r"^[A-Z]{2}$")
    name_en: str
    name_ar: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    region: str
    road_factor: float = Field(ge=1.2, le=1.5)


class City(BaseModel):
    id: str
    name_en: str
    name_ar: str
    country_code: str
    point: Point
    industrial: bool = False


class Hub(BaseModel):
    id: str
    type: HubType
    name_en: str
    name_ar: str
    country_code: str
    point: Point
    unlocode: str | None = None
    iata: str | None = None
    serves_countries: list[str]
    notes: str | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    as_of: str | None = None  # YYYY-MM the coordinates/attributes were last reviewed


class NearestHub(Hub):
    distance_km: float


class DistanceResult(BaseModel):
    mode: Literal["road", "sea", "air"]
    distance_km: float
    straight_line_km: float
    duration_hours: float
    method: str
    road_factor: float | None = None
    via: list[str] = []
    is_estimate: bool = True
    avoided: list[str] = []
    confidence: Literal["low", "medium", "high"] | None = None
    as_of: str | None = None
