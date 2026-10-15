from .data import Dataset
from .geometry import haversine_km
from .models import DistanceResult
from .sea import DATA_AS_OF, DATA_CONFIDENCE, sea_distance_km

SPEED_KMH = {"road": 55.0, "sea": 26.0, "air": 800.0}
AIR_OVERHEAD_H = 3.0


def road_factor_at(ds: Dataset, lat: float, lon: float, default: float, country: str | None = None):
    if country and country.upper() in ds.country_by_code:
        return ds.country_by_code[country.upper()].road_factor
    if not ds.cities:
        return default
    nearest = min(ds.cities, key=lambda c: haversine_km(lat, lon, c.point.lat, c.point.lon))
    return ds.country_by_code[nearest.country_code].road_factor if nearest else default


def compute_distance(
    ds: Dataset,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    mode: str,
    default_road_factor: float = 1.3,
    country: str | None = None,
    avoid: frozenset[str] = frozenset(),
) -> DistanceResult:
    straight = haversine_km(lat1, lon1, lat2, lon2)
    if mode == "road":
        f = road_factor_at(ds, lat1, lon1, default_road_factor, country)
        km = straight * f
        return DistanceResult(
            mode="road", distance_km=round(km, 1), straight_line_km=round(straight, 1),
            duration_hours=round(km / SPEED_KMH["road"], 1), method="haversine x country road factor",
            road_factor=f,
        )
    if mode == "air":
        return DistanceResult(
            mode="air", distance_km=round(straight, 1), straight_line_km=round(straight, 1),
            duration_hours=round(straight / SPEED_KMH["air"] + AIR_OVERHEAD_H, 1),
            method="great-circle",
        )
    km, via = sea_distance_km(lat1, lon1, lat2, lon2, avoid)
    km = max(km, straight)
    return DistanceResult(
        mode="sea", distance_km=round(km, 1), straight_line_km=round(straight, 1),
        duration_hours=round(km / SPEED_KMH["sea"], 1), method="shipping-lane waypoint graph",
        via=via, avoided=sorted(avoid), confidence=DATA_CONFIDENCE, as_of=DATA_AS_OF,
    )
