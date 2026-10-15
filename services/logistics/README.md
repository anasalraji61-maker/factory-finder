# logistics (port 8102)

Landed-cost engine: origin inland -> main leg (sea LCL/FCL, air, rail, road) -> destination hub -> duties/VAT -> destination inland, with FX, carriers directory and warnings. Money is `Decimal`; all rates are an approximate table, verify with a customs broker.

Endpoints: `GET /health`, `POST /v1/quotes/landed-cost`, `GET /v1/fx/rates`, `POST /v1/fx/convert`, `GET /v1/carriers`, `GET /v1/hs/search?q=&limit=`, `GET /v1/hs/{code}` (HS finder: curated ~700 6-digit subheadings in `data/hs_codes.json`, indicative only, confirm with a customs broker; optional `destination_country` selects the duty table for `typical_duty_percent_hint`). Contract: `contracts/openapi/logistics.yaml`.

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


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): always 200 (no database). Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

## Data round 3
- `data/duties.json`: 70 destinations; new entries carry `source`, `as_of`, `confidence`, `duty_range_pct`, `vat_range_pct`, `label` ("indicative, verify with broker") and `de_minimis` (warning only, never applied to totals).
- Every option has an optional `sensitivity` (freight / fx / combined low-base-high); FX buckets live in `data/fx_volatility.json` (judgment-based stress sizes, not forecasts).

## Import-compliance advisor (indicative, `/v1/compliance/*`)
For a destination country (+ optional HS code or category, origin, incoterm, mode, new/used, dangerous goods) it returns: (a) a bilingual (ar+en) documents checklist with requirement level, stage and lead days (commercial invoice, packing list, B/L / AWB / CMR / rail note, certificate of origin, health/phyto/halal, and conformity or advance-information programs: Iraq COSQC conformity, Saudi SABER PCoC/SCoC, UAE ECAS, GCC conformity, Egypt ACI/ACID + GOEIC, Turkey TAREKS, EU EORI/ICS2/CE/REACH/CBAM, US ISF/FDA/FCC/CPSC); (b) restriction flags (prohibited / licence_required / restricted / enhanced_scrutiny; `scope` general|product|origin|condition); (c) incoterm split per landed-cost leg (`payer` buyer|seller, derived from the same `BUYER_STAGES` table as the quote engine) plus a suggestion; (d) clearance timeline (pre-shipment, clearance, total; transit excluded); (e) an `indicative` block (source, `as_of` 2026-10, confidence, "verify with a licensed customs broker").

Endpoints: `POST /v1/compliance/checklist`, `GET /v1/compliance/countries`, `GET /v1/compliance/countries/{code}`, `GET /v1/compliance/incoterms[?incoterm=]`. Landed-cost quote responses also carry an optional `compliance_hint` (recommended mode, quote incoterm).

Data: `data/compliance.json` (generated once from reviewed tables, now edited by hand). Profiles: IQ, SA, AE, KW, QA, OM, BH, TR, JO, EG, EU (27 members resolve to it), US; any other country returns the generic `ZZ` baseline with `covered=false`, confidence low. Product resolution: HS chapter -> product group (every chapter 01-97 maps to exactly one group), else `category` alias, else generic goods (confidence drops, assumption listed). Each profile has `source`, `as_of`, `confidence`; documents/restrictions may override confidence and carry filters (`groups`, `hs_prefixes`, `origins`, `modes`, `condition`). Country documents override same-id global ones.

Adding a country: add a profile under `countries` (same shape as IQ), run `tests/test_compliance.py` (shape + ar/en parity tests iterate every profile). No network, no env vars.

## Environment reference (complete)
Every setting in `src/ff_logistics/config.py` (`Settings`, case-insensitive env names). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_LOGISTICS_GEO_PROVIDER` | http |
| `FF_LOGISTICS_GEO_URL` | http://localhost:8103 |
| `FF_LOGISTICS_GEO_CACHE_TTL_SECONDS` | 600.0 |
| `FF_LOGISTICS_FX_PROVIDER` | mock |
| `FF_LOGISTICS_FX_URL` | https://api.frankfurter.dev/v1/latest |
| `FF_LOGISTICS_FX_CACHE_TTL_SECONDS` | 21600 |
| `FF_INTERNAL_TOKEN` | unset |
| `FF_LOGISTICS_FREIGHT_PROVIDER` | mock |
| `FF_LOGISTICS_FREIGHT_URL` | unset |
| `FF_LOGISTICS_FREIGHT_API_KEY` | unset |
| `FF_LOGISTICS_FREIGHT_MIN_INTERVAL_S` | 3.0 |
| `FF_LOGISTICS_FREIGHT_CACHE_TTL_SECONDS` | 21600 |
| `FF_LOGISTICS_FREIGHT_MAX_CALLS_PER_QUOTE` | 6 |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default).

Read straight from the environment (not in `Settings`): `FF_LOGISTICS_KILL_SWITCH` and `FF_LOGISTICS_FREIGHT_DISABLED` (truthy = the live freight adapter is skipped and the mock is used).

## Forwarder quote override (`freight_override`)
Optional field on `POST /v1/quotes/landed-cost`: `{amount, currency, source: "forwarder_quote", quote_id, valid_until, mode_family?}` (the object returned by freight `GET /v1/freight/quotes/{id}/landed-cost-input`; no service imports the other, the client relays it). When valid and `valid_until` is in the future, the main-leg line of every option (or only the options of `mode_family`) is that exact price: `estimate=false`, no `range`, extra `quoted=true`, source `forwarder_quote <quote_id>`, original amount in the quote currency (converted through the FX adapter; exact when it equals the display currency). Expired, malformed, non-`forwarder_quote` or FX-unknown overrides are ignored (never a 422) with an assumption note "Forwarder freight quote ignored (...)". The quote is not validated against the cargo or lane.
