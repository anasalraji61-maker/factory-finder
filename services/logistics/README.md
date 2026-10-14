# logistics (port 8102)

Landed-cost engine: origin inland -> main leg (sea LCL/FCL, air, rail, road) -> destination hub -> duties/VAT -> destination inland, with FX, carriers directory and warnings. Money is `Decimal`; all rates are an approximate table, verify with a customs broker.

Endpoints: `GET /health`, `POST /v1/quotes/landed-cost`, `GET /v1/fx/rates`, `POST /v1/fx/convert`, `GET /v1/carriers`. Contract: `contracts/openapi/logistics.yaml`.

Layout: `domain/` pure engine (cargo, incoterms, duties, warnings, engine), `clients/geo.py` (Protocol + httpx + MockGeo), `adapters/fx.py` (mock + ECB/Frankfurter with cache and fallback), `data/*.json` (lanes, handling, duties, routes, carriers).

Recommended option: lowest `0.6*cost + 0.4*time` score (min-max normalised across options).

Run: `cd services/logistics && ../../.venv/bin/python -m pytest -q`; `uvicorn ff_logistics.main:app --port 8102`.

Env: `FF_LOGISTICS_GEO_PROVIDER` (http|mock, default http), `FF_LOGISTICS_GEO_URL` (http://localhost:8103), `FF_LOGISTICS_FX_PROVIDER` (mock|ecb), `FF_LOGISTICS_FX_URL`, `FF_LOGISTICS_FX_CACHE_TTL_SECONDS`, `FF_INTERNAL_TOKEN` (optional).

## Live freight rates (OFF by default, UNVERIFIED)
`adapters/freight.py`: `FreightRateProvider` (`MockFreight` = built-in tables, `HttpFreightProvider` = Freightos-style
estimator). Quotes feed the main-leg line (midpoint, range from the quote, never tighter than +-5%, marked estimate with
source+timestamp); any error falls back to the tables and adds an assumption line. Env: `FF_LOGISTICS_FREIGHT_PROVIDER`
(mock|http), `_FREIGHT_URL`, `_FREIGHT_API_KEY`, `_FREIGHT_DISABLED`, `FF_LOGISTICS_KILL_SWITCH`, `_FREIGHT_MIN_INTERVAL_S`,
`_FREIGHT_CACHE_TTL_SECONDS`, `_FREIGHT_MAX_CALLS_PER_QUOTE`.
