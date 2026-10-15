# sourcing

Searches supplier sources (products, raw materials, production lines new/used), normalizes,
de-duplicates, enriches with trust bands and ranks. Bilingual (Arabic + English) search.

## Run / test
```
cd services/sourcing
../../.venv/bin/python -m pytest -q
../../.venv/bin/ruff check .
../../.venv/bin/uvicorn ff_sourcing.main:app --port 8101   # compose + every client default use 8101
```

## Endpoints (contract: `contracts/openapi/sourcing.yaml`)
`GET /health` · `GET /v1/search` · `GET /v1/listings/{id}` · `GET /v1/suppliers/{id}` ·
`GET /v1/categories` · `GET /v1/sources` · `GET /v1/listings/{id}/price-history` · `GET /v1/listings/{id}/similar` ·
`GET /v1/recommendations` ·
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

## Moderation (native listings)
Statuses `pending_review` and `hidden` take a listing out of search/detail/supplier counts for everyone but its owner
(owner sees `status`, `moderation_source` auto|report|admin, `moderation_reason`); they cannot be published (409
`under_moderation`). Code: `domain/moderation.py`, `api/moderation.py`, data `data/prohibited_goods.json`.
- **Screening** on create/update (title, descriptions, unit, specs; ar+en): contact info/links (URL, email, phone >= 9
  digits incl. Arabic-Indic, messaging handles) and banned goods (word-level match, Arabic prefixes/plurals handled; edit
  the JSON to extend). Flagged create -> `pending_review`; flagged update of a draft/published/archived listing -> goes
  offline; owner fixing an auto-flagged listing lifts it and restores the previous status. Reasons name the field and
  kind only, never the matched text.
- **Reports** `POST /v1/listings/{id}/report` (`X-User-Id` from gateway; 401 without): reason enum, optional details (500
  chars, emails/links/phones redacted). Published listings only (else 404). Dedupe per reporter+listing (repeat = same
  202), 10/hour per reporter (429), own listing 409. Reporter stored only as keyed hash. 3 distinct open reports ->
  `pending_review` (`REPORT_REVIEW_THRESHOLD`, 0 = off).
- **Admin** (`X-Admin-Token` = `FF_SOURCING_ADMIN_TOKEN`; 404 while unset, 401 wrong): `GET /v1/admin/moderation/reports`,
  `GET /v1/admin/moderation/listings`, `POST .../listings/{id}/hide {reason}`, `POST .../listings/{id}/restore` (back to
  the status before moderation; open reports become actioned/dismissed). With `FF_INTERNAL_TOKEN` set, report and admin
  paths also need `X-Internal-Token`. Gateway routing: `docs/requests/sourcing-moderation-gateway.md`.
Env: `ADMIN_TOKEN`, `REPORT_RATE_PER_HOUR`, `REPORT_REVIEW_THRESHOLD`, `REPORTER_HASH_KEY`. Migration `0002_moderation`.

## Env (prefix `FF_SOURCING_`)
`ENABLED_SOURCES` (default `mock,native`; e.g. `mock,native,alibaba`), `ADAPTER_TIMEOUT_S` (3), `CACHE_TTL_S` (60),
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

## Licensed REST provider (generic, config-driven)
`adapters/licensed_rest.py` loads a JSON mapping (endpoint templates, auth header|query|bearer from an env var NAME,
pagination page|offset|cursor, field mapping, currency/unit normalization, image host allowlist, limits, quality bounds).
Examples (fictional providers, refused at runtime): `examples/licensed/*.mapping.json`. Validate offline:
`python -m ff_sourcing.licensed_validate mapping.json --sample response.json`. Quality rules: `domain/quality.py`
(dedupe by supplier+title, price sanity, currency detection). Enable: `FF_SOURCING_LICENSED_MAPPINGS` + id in
`FF_SOURCING_ADAPTERS`; see `docs/decisions/sourcing-licensed-provider.md`. Failure falls back to mock with a warning.

## Price history
`GET /v1/listings/{id}/price-history?days=1..365&bucket=day|week|month` -> `points` (bucket start, avg/min/max, n), `summary`,
`trend` (`direction` up|down|flat within +-1%, `change_pct`, `insufficient_data` when < 2 observations/buckets) and `hints`
(`suggested_target` = period low, `at_period_low`; for watchlist/alert target suggestions). Non-mock listings are observed
(min unit price) on search pages, detail fetches and native publish/update (`price_history.py`, table `price_observations`,
migration `0003`): same price+currency within 6 h is not re-recorded, max 500 points and 400 days per listing, failures never
break the request. Mock-catalog listings return a deterministic seeded daily series ending at the current price
(`synthetic: true`; `domain/pricehistory.py`). Env: `PRICE_HISTORY_DEDUPE_HOURS`, `PRICE_HISTORY_MAX_POINTS`, `PRICE_HISTORY_RETENTION_DAYS`.

## Similar / recommendations
`domain/reco.py` (pure scoring) + `SourcingService.similar/recommendations`. Same kind only; score = category 0.30 + title/spec
token overlap 0.30 + price band (same currency, within 2x) 0.15 + condition 0.05 + different supplier +0.08 (same supplier -0.08)
+ trust band (green +0.10, yellow +0.03, red -0.25) + verified 0.02; minimum 0.25. Each item has `reasons[]` with `code`, `en`, `ar`.
Bounded: <= 300 candidates scored, trust looked up for the best 60 only. `/v1/recommendations?ref=<ids, most recent first, max 20>&country=`:
stateless (client sends its recent ids; nothing stored/logged per user), weight decays with position, <= 3 per supplier, `country`
= preferred origin (+0.05, not a filter), no usable ref -> top trusted listings. Gateway: public GET, routed to sourcing.

## Supplier analytics (native listings)
Privacy-safe, aggregate only: table `listing_stats_daily` (listing_id, day, metric, count, uniques; migration `0004`), no IP/user
id/UA ever stored or logged. Metrics: `impression` (native listing on a served search page, server side), `view` / `contact_click` /
`share` (client `POST /v1/listings/{id}/events {type}` -> 202 `{counted}`), `report` (new non-duplicate report), `watchlist_add`
(internal hook only: `app.state.analytics.bump(listing_id, "watchlist_add")`, no HTTP endpoint; notifications may call it once
an internal route is agreed). Events: viewer = `X-User-Id` else `X-Client-Ip` (both gateway-set) -> HMAC keyed by a secret **and the
UTC day** (rotates daily, wiped at day change/restart), kept only in bounded memory: same viewer counts once per listing+type per
30 min, 60 events/min per IP and per user (429), unique-viewer set capped (2000 per listing+type+day, 20000 sets, saturates =
undercounts), dedupe map 50k entries. Only published native listings count; anything else answers the same 202 `counted:false`.
`GET /v1/my/analytics?days=7|30|90&listing_id=` (X-Supplier-Id; only own listings, others 404): `totals`, `previous_totals`,
`change_pct`, zero-filled daily `series`, `conversion` (view->contact, impression->view, capped at 1), `unique_viewers` (sum of
daily estimates), top-20 `listings` table. Retention 400 days (purged opportunistically, hourly); rows are deleted with the
listing and with account erasure (`counts.analytics_rows_deleted`). Env: `ANALYTICS_HASH_KEY` (empty = random per process),
`ANALYTICS_DEDUPE_S`, `ANALYTICS_EVENT_RATE_PER_MIN`, `ANALYTICS_UNIQUE_CAP`, `ANALYTICS_MAX_SETS`, `ANALYTICS_DEDUPE_MAX`,
`ANALYTICS_RETENTION_DAYS`. Code: `analytics.py`, `api/analytics.py`. Gateway: events are public (optional bearer) and get a
trusted-proxy-resolved `X-Client-Ip`.

## Environment reference (complete)
Every setting in `src/ff_sourcing/config.py` (`Settings`, case-insensitive env names; empty values count as unset). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_SOURCING_ENABLED_SOURCES` | mock,native |
| `FF_SOURCING_ADAPTERS` | unset |
| `FF_SOURCING_ADAPTER_TIMEOUT_S` | 3.0 |
| `FF_SOURCING_LICENSED_MAPPINGS` | unset |
| `FF_SOURCING_LICENSED_ALLOW_EXAMPLE` | False |
| `FF_SOURCING_CACHE_TTL_S` | 60.0 |
| `FF_SOURCING_TRUST_CACHE_TTL_S` | 300.0 |
| `FF_SOURCING_RECO_CACHE_TTL_S` | 60.0 |
| `FF_SOURCING_RECO_RESPONSE_TTL_S` | 30.0 |
| `FF_SOURCING_RECO_CACHE_MAX` | 256 |
| `FF_SOURCING_PROVIDER_CONCURRENCY` | 6 |
| `FF_SOURCING_RECO_BUDGET_S` | 5.0 |
| `FF_SOURCING_DATABASE_URL` | sqlite+aiosqlite:///./sourcing.db |
| `FF_SOURCING_DB_AUTO_CREATE` | unset |
| `FF_SOURCING_INTERNAL_TOKEN` | unset |
| `FF_SOURCING_MAX_LISTINGS_PER_SUPPLIER` | 200 |
| `FF_SOURCING_CREATE_RATE_PER_HOUR` | 30 |
| `FF_SOURCING_ADMIN_TOKEN` | unset |
| `FF_SOURCING_REPORTER_HASH_KEY` | ff-sourcing-reporter |
| `FF_SOURCING_REPORT_RATE_PER_HOUR` | 10 |
| `FF_SOURCING_REPORT_REVIEW_THRESHOLD` | 3 |
| `FF_SOURCING_PRICE_HISTORY_DEDUPE_HOURS` | 6.0 |
| `FF_SOURCING_PRICE_HISTORY_MAX_POINTS` | 500 |
| `FF_SOURCING_PRICE_HISTORY_RETENTION_DAYS` | 400 |
| `FF_SOURCING_ANALYTICS_HASH_KEY` | unset |
| `FF_SOURCING_ANALYTICS_DEDUPE_S` | 1800.0 |
| `FF_SOURCING_ANALYTICS_EVENT_RATE_PER_MIN` | 60 |
| `FF_SOURCING_ANALYTICS_UNIQUE_CAP` | 2000 |
| `FF_SOURCING_ANALYTICS_MAX_SETS` | 20000 |
| `FF_SOURCING_ANALYTICS_DEDUPE_MAX` | 50000 |
| `FF_SOURCING_ANALYTICS_RETENTION_DAYS` | 400 |
| `FF_SOURCING_TRUST_MODE` | mock |
| `FF_SOURCING_TRUST_BASE_URL` | http://localhost:8104 |
| `FF_SOURCING_TRUST_TIMEOUT_S` | 0.8 |
| `FF_SOURCING_USER_AGENT` | FactoryFinderBot/0.1 (+https://github.com/factory-finder;... |
| `FF_SOURCING_MIN_REQUEST_INTERVAL_S` | 3.0 |
| `FF_SOURCING_ALIBABA_APP_KEY` | unset |
| `FF_SOURCING_ALIBABA_APP_SECRET` | unset |
| `FF_SOURCING_ALIBABA_API_BASE` | https://openapi-api.alibaba.com |
| `FF_SOURCING_ALIEXPRESS_APP_KEY` | unset |
| `FF_SOURCING_ALIEXPRESS_APP_SECRET` | unset |
| `FF_SOURCING_ALIEXPRESS_TRACKING_ID` | unset |
| `FF_SOURCING_ALIEXPRESS_API_BASE` | https://api-sg.aliexpress.com/sync |
| `FF_SOURCING_MIC_API_KEY` | unset |
| `FF_SOURCING_MIC_API_BASE` | unset |
| `FF_SOURCING_MIC_ALLOW_PUBLIC_PAGES` | False |
| `FF_SOURCING_S1688_APP_KEY` | unset |
| `FF_SOURCING_S1688_APP_SECRET` | unset |
| `FF_SOURCING_S1688_API_BASE` | https://gw.open.1688.com/openapi |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default), `FF_ENV=production` refuses to start without `FF_INTERNAL_TOKEN` (see `docs/OPS.md`).

Read straight from the environment (not in `Settings`): `FF_SOURCING_KILL_SWITCH` (all real adapters), `FF_SOURCING_ALIBABA_OPENAPI_DISABLED`, `FF_SOURCING_ALIBABA_ACCESS_TOKEN` (the `alibaba_openapi` adapter also reads `FF_SOURCING_ALIBABA_APP_KEY` / `FF_SOURCING_ALIBABA_APP_SECRET` from the environment).
