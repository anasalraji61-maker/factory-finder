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
`GET /v1/categories` · `GET /v1/sources` ·
supplier-owned listings: `POST|GET /v1/my/listings` · `GET|PUT|DELETE /v1/my/listings/{id}` ·
`POST /v1/my/listings/{id}/publish|unpublish`

## Layout
- `domain/`: pure logic. `text.py` (Arabic normalization, stemming, bilingual synonyms), `search.py`
  (filters, relevance, de-dup, ranking, pagination), `categories.py`, `cache.py` (TTL).
- `adapters/`: `base.py` (`SourceAdapter`), `registry.py` (enable/disable), `mock.py` (60-listing
  catalog in `data/catalog.json`), real stubs `alibaba`, `made_in_china`, `aliexpress`, `source_1688`
  built on `http_base.py` (rate limit, robots.txt, cache, signing). Real adapters are OFF by default.
- `clients/trust.py`: trust service client (800 ms timeout, failure -> band `unknown`) + mock.
- `service.py`: concurrent fan-out with per-adapter timeout and failure isolation.

## Search quality
- Query pipeline (`domain/text.py`): NFKD + accent/diacritic/tatweel strip, alef/ya/ta-marbuta (and Persian
  letter) unification, Arabic clitic/`ال` stripping, English plural stripping, one token per Chinese character.
  Greedy longest-phrase expansion through a curated Arabic (incl. Iraqi dialect) / English / Chinese synonym table.
- Typo tolerance: unknown words >= 4 letters are corrected to a unique known term, or fuzzy-matched against
  document tokens (edit distance 1, 2 when both >= 8 letters; same first letter; no 4-letter substitutions
  such as tile/tire; never digits).
- Query terms are AND-ed. Per-term field weights: title 1.0 > category 0.6 > description 0.35 > supplier/city 0.2
  (typo hit x0.8). Score = `0.62 relevance + 0.10 exact title phrase + 0.12 trust band + 0.03 verified + 0.13 price fit`;
  ties break by id.
- `sort` = `relevance` (default) | `price_asc` | `price_desc` | `trust` | `moq`. Response `facets`
  (kind, condition, origin_country, category counts) cover the whole matched set, not just the page.

## Native (supplier-owned) listings
Persistent `native` source (SQLAlchemy async, table `native_listings`, Alembic in `migrations/`, see `docs/DB.md`).
Caller identity = gateway-set `X-Supplier-Id` (verified claims only; 403 `supplier_required` without it; with
`FF_INTERNAL_TOKEN` configured, `/v1/my/*` also needs `X-Internal-Token`, else 401). Listings start `draft`, only
`published` ones appear in search/detail (id `nat_xxxxxxxx`, `source: native`); `unpublish` archives. Publish needs a
non-red trust band and fails closed (503 `trust_unavailable`) if trust is down/unknown. Caps: 200 listings per supplier
(409), 30 creates/hour per supplier per process (429 + Retry-After). Others' listings answer 404. Code: `domain/native.py`
(validation), `adapters/native.py` (store + adapter), `native_service.py`, `api/my.py`.
Env: `DATABASE_URL`, `DB_AUTO_CREATE`, `MAX_LISTINGS_PER_SUPPLIER`, `CREATE_RATE_PER_HOUR`, `INTERNAL_TOKEN`.

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
`GET /ready` (unauthenticated, exempt from the internal token): 200 when the database is reachable, else 503. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).
