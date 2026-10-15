from typing import Annotated, Literal

from fastapi import APIRouter, Query

from ..config import get_settings
from ..domain import search
from ..domain.data import get_dataset
from ..domain.distance import compute_distance
from ..domain.models import City, Country, DistanceResult, Hub, NearestHub
from ..domain.sea import SeaRouteUnavailable, parse_avoid
from .errors import ApiError

router = APIRouter(prefix="/v1")

HubTypeParam = Literal["sea", "air", "rail", "land", "land_border", "consolidation"]
Lat = Annotated[float, Query(ge=-90, le=90)]
Lon = Annotated[float, Query(ge=-180, le=180)]
CountryParam = Annotated[str | None, Query(max_length=8)]


def _check_country(code: str | None) -> None:
    if code and code.upper() not in get_dataset().country_by_code:
        raise ApiError(404, "country_not_found", f"Unknown country code: {code}")


@router.get("/countries")
def countries() -> dict[str, list[Country] | int]:
    items = get_dataset().countries
    return {"items": items, "total": len(items)}


@router.get("/cities")
def cities(
    q: Annotated[str | None, Query(max_length=100)] = None,
    country: CountryParam = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, list[City] | int]:
    _check_country(country)
    found = search.search_cities(get_dataset(), q, country)
    return {"items": found[:limit], "total": len(found)}


@router.get("/hubs")
def hubs(country: CountryParam = None, type: HubTypeParam | None = None) -> dict[str, list[Hub] | int]:
    _check_country(country)
    found = search.filter_hubs(get_dataset(), country, type)
    return {"items": found, "total": len(found)}


@router.get("/hubs/nearest")
def hubs_nearest(
    lat: Lat,
    lon: Lon,
    type: HubTypeParam | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
    country: CountryParam = None,
) -> dict[str, list[NearestHub]]:
    _check_country(country)
    return {"items": search.nearest_hubs(get_dataset(), lat, lon, type, limit, country)}


@router.get("/distance")
def distance(
    from_lat: Lat,
    from_lon: Lon,
    to_lat: Lat,
    to_lon: Lon,
    mode: Literal["road", "sea", "air"] = "road",
    country: CountryParam = None,
    avoid: Annotated[str | None, Query(max_length=200)] = None,
) -> DistanceResult:
    _check_country(country)
    try:
        avoided = parse_avoid(avoid)
    except ValueError as e:
        raise ApiError(422, "unknown_chokepoint", str(e)) from e
    try:
        return compute_distance(
            get_dataset(), from_lat, from_lon, to_lat, to_lon, mode,
            get_settings().default_road_factor, country, avoided if mode == "sea" else frozenset(),
        )
    except SeaRouteUnavailable as e:
        raise ApiError(422, "sea_route_unavailable", str(e)) from e
