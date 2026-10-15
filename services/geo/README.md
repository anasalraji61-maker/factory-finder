# geo (port 8103)

Static-data service: countries, cities (Arabic/English search), logistics hubs (sea ports with UN/LOCODE, cargo airports `air:<IATA>`, rail terminals, land border crossings, consolidation hubs), nearest-hub lookup and distance estimates (road / sea / air).

## Run
```
cd services/geo && ../../.venv/bin/python -m uvicorn ff_geo.main:app --port 8103 --app-dir src
../../.venv/bin/python -m pytest -q && ../../.venv/bin/ruff check .
```

## Endpoints
`GET /health`, `/v1/countries`, `/v1/cities?q=&country=&limit=`, `/v1/hubs?country=&type=`, `/v1/hubs/nearest?lat=&lon=&type=&limit=&country=`, `/v1/distance?from_lat=&from_lon=&to_lat=&to_lon=&mode=road|sea|air&country=`. Contract: `contracts/openapi/geo.yaml`.

## Layout
- `domain/` pure logic (`text.normalize`, `geometry`, `search`, `sea` waypoint graph, `distance`, `data` loader + validation at startup)
- `api/` thin routers + standard error body; `data/*.json` bundled datasets.

## Notes
- Arabic search normalization: strips diacritics/tatweel, unifies أإآ->ا, ى->ي, ة->ه.
- Distances are estimates: road = straight-line x country road factor; sea = lane-graph approximation.
- Env (prefix `FF_GEO_`): `PORT`, `DEFAULT_ROAD_FACTOR`. No network access anywhere.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 if the bundled dataset fails to load. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

## Sea graph (data round 3)
`domain/sea.py` has 182 lane nodes and 159 sea hubs. Access nodes farther than 400 km are ignored (except the nearest) so ports never jump overland. `tests/test_sea_properties.py` checks distance >= great-circle, symmetry and sane detour ratios.

## Environment reference (complete)
Every setting in `src/ff_geo/config.py` (`Settings`, case-insensitive env names). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_GEO_PORT` | 8103 |
| `FF_GEO_INTERNAL_TOKEN` | unset |
| `FF_GEO_DEFAULT_ROAD_FACTOR` | 1.3 |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default).

Sea `avoid`: comma-separated chokepoints (`suez, bab_el_mandeb, hormuz, malacca, panama, gibraltar, bosphorus`) removed from the lane graph; with `avoid` only each endpoint's nearest lane node is used. Unknown id -> 422 `unknown_chokepoint`; no lane left -> 422 `sea_route_unavailable`. Sea results carry `confidence: low`, `as_of: 2026-10`; hubs carry `confidence`/`as_of` (never "high" = never claimed verified). Network validation: `tests/test_sea_network.py`.

## Land-mask check (QA follow-up)
`tests/test_sea_landmask.py` carries ~20 hand-written, deliberately *inset* landmass polygons (Africa, Iberia, W/Central Europe, Italy, Great Britain, Jutland, Anatolia, Arabia, India, Malay peninsula, Baja, Panama, US east/west, South America, Australia). Every lane node and 80 great-circle samples per edge must stay outside them; the `ALLOW` set (currently empty) is for explicit per-edge strait exceptions. It found and we fixed six edges that cut peninsulas (Malay, Kerala, Panama/Azuero, Baja, Jutland, Oman/Ras al Hadd) by adding 8 waypoints. Limits: polygons are inset 0.3-1.5 deg, so grazing a coast by < ~30-100 km is NOT detected; most islands (Sicily core only, Sardinia, Japan, Indonesia, Philippines, Sri Lanka, Taiwan) are not masked; it is a sanity net, not a coastline model. Sea data stays `confidence: low`.
