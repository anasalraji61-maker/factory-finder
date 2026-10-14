# trust (port 8104)

Explainable supplier trust score 0-100 with band green (>=75) / yellow (50-74) / red (<50) / unknown (<4 known signals). Hard caps: sanctions hit -> red, <=20; dispute rate >=8% -> <=69, >=15% -> <=49; price < 0.4x market -> <=59. Every factor has a signed integer impact plus `explanation` / `explanation_ar`.

v2 (model `trust-v2`): extra signals (business-licence status, certificate records with expiry, repeat-buyer rate, response time, refund rate, recency-weighted disputes, on-platform deal outcomes, storefront age, accepted buyer reports); Bayesian shrinkage for ratings and deal completion; `confidence` (0-100 int, evidence coverage x sample depth), `data_gaps` (missing signals, en+ar; missing never lowers the score), `flags` (price_anomaly, certification_expired, ...). Hard fail: `sanctions_hit` or `blocked` -> red, <=20.

Endpoints: `GET /v1/trust/suppliers/{id}/history` (oldest-first; deterministic mock points + stored snapshots), `POST /v1/trust/suppliers/{id}/report` (needs `X-User-Id`; type enum + text<=1000; stored `pending_review`, no score effect until a moderator accepts via `TrustService.review_report`; 429 + Retry-After past `FF_TRUST_REPORT_RATE_LIMIT`/`FF_TRUST_REPORT_RATE_WINDOW_SECONDS`, default 5/hour/user). Stores are in-memory. Also: `GET /v1/trust/suppliers/{id}` (TTL cache), `GET /v1/trust/suppliers:batch?ids=a,b`, `POST /v1/trust/evaluate`, `GET /health`. Contract: `contracts/openapi/trust.yaml`.

Run: `uvicorn ff_trust.main:app --port 8104`. Test: `../../.venv/bin/python -m pytest -q`.

Env: `FF_TRUST_ADAPTER` (mock default; alibaba/made_in_china are disabled stubs), `FF_TRUST_CACHE_TTL_SECONDS` (300), `FF_TRUST_MAX_BATCH` (50), `FF_INTERNAL_TOKEN` (optional), `FF_TRUST_REPORT_RATE_LIMIT` (5), `FF_TRUST_REPORT_RATE_WINDOW_SECONDS` (3600), `FF_TRUST_HISTORY_MONTHS` (12).
Mock ids: any id works (sha256-derived); curated `sup_demo_gold|avg|scam|sanctioned`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): always 200 (no database). Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

## Review summary signal (rfq)
Optional signal `review_summary` (count, average, histogram, sub_ratings, completed_deals; `rfq.yaml#ReviewSummary`) adds the factor `platform_reviews` (weight 6, bounded +-6): Bayesian shrinkage (`platform_review_prior_weight` 8 towards `review_prior_mean`), 30% blended with the mean sub-rating, then linearly dampened below 10 reviews (`platform_review_full_n`); evidence line en+ar says "small sample dampened". Absent summary = no factor, never a data gap, score unchanged. It is separate from `rating_avg` (marketplace ratings), so nothing is double counted. `evaluate` accepts it inline.
`clients/reviews.py`: `HttpReviewsClient` (GET `{base}/v1/suppliers/{id}/review-summary`, timeout, 60 s cache, any error/non-200/bad JSON -> None = score without it), `MockReviewsClient` (deterministic). Env: `FF_TRUST_REVIEWS_SOURCE` (`off` default | `mock` | `http`), `FF_TRUST_REVIEWS_BASE_URL` (http://rfq:8105), `FF_TRUST_REVIEWS_TIMEOUT_SECONDS` (2), `FF_TRUST_REVIEWS_CACHE_TTL_SECONDS` (60). Scores are cached by the service TTL (300 s), so new reviews show up within that window.
