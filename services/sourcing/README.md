# sourcing

Searches supplier sources (products, raw materials, production lines new/used), normalizes,
de-duplicates, enriches with trust bands and ranks. Bilingual (Arabic + English) search.

## Run / test
```
cd services/sourcing
../../.venv/bin/python -m pytest -q
../../.venv/bin/ruff check .
../../.venv/bin/uvicorn ff_sourcing.main:app --port 8002
```

## Endpoints (contract: `contracts/openapi/sourcing.yaml`)
`GET /health` · `GET /v1/search` · `GET /v1/listings/{id}` · `GET /v1/suppliers/{id}` ·
`GET /v1/categories` · `GET /v1/sources`

## Layout
- `domain/`: pure logic. `text.py` (Arabic normalization, stemming, bilingual synonyms), `search.py`
  (filters, relevance, de-dup, ranking, pagination), `categories.py`, `cache.py` (TTL).
- `adapters/`: `base.py` (`SourceAdapter`), `registry.py` (enable/disable), `mock.py` (60-listing
  catalog in `data/catalog.json`), real stubs `alibaba`, `made_in_china`, `aliexpress`, `source_1688`
  built on `http_base.py` (rate limit, robots.txt, cache, signing). Real adapters are OFF by default.
- `clients/trust.py`: trust service client (800 ms timeout, failure -> band `unknown`) + mock.
- `service.py`: concurrent fan-out with per-adapter timeout and failure isolation.

## Ranking
`0.55 * relevance + 0.25 * trust band + 0.20 * price fit (percentile within category)`.
Query terms are AND-ed; each term may match any of its synonyms (title hit = 3, category/supplier = 1).

## Env (prefix `FF_SOURCING_`)
`ENABLED_SOURCES` (default `mock`; e.g. `mock,alibaba`), `ADAPTER_TIMEOUT_S` (3), `CACHE_TTL_S` (60),
`TRUST_MODE` (`mock`|`http`|`off`), `TRUST_BASE_URL`, `TRUST_TIMEOUT_S` (0.8), `MIN_REQUEST_INTERVAL_S` (3),
`USER_AGENT`, and credentials (empty = adapter unconfigured): `ALIBABA_APP_KEY/_APP_SECRET`,
`ALIEXPRESS_APP_KEY/_APP_SECRET/_TRACKING_ID`, `MIC_API_BASE/_API_KEY/_ALLOW_PUBLIC_PAGES`,
`S1688_APP_KEY/_APP_SECRET`. Never commit values.

## Licensed/official API adapters (Phase 4 prep, OFF by default, UNVERIFIED)
`adapters/http_provider.py`: `ProviderConfig` (base URL, key env-var NAME, field-mapping table, >=3 s/host
limit, cache TTL, honest UA, ToS note, kill-switch env) + `HttpProviderAdapter`. `alibaba_openapi.py` is the
Alibaba Open Platform skeleton (assumed shape, replace `tests/fixtures/*.json` with real recordings).
Enable with `FF_SOURCING_ADAPTERS=alibaba_openapi`; extra env: `ALIBABA_ACCESS_TOKEN`, `ALIBABA_OPENAPI_DISABLED`,
`KILL_SWITCH` (all real adapters). A failing real adapter yields mock results plus `sources[].warning`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): always 200 (no database). Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).
