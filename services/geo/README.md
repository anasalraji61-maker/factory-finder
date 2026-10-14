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
`domain/sea.py` has 150 lane nodes and 138 sea hubs. Access nodes farther than 400 km are ignored (except the nearest) so ports never jump overland. `tests/test_sea_properties.py` checks distance >= great-circle, symmetry and sane detour ratios.
