# sourcing: amplification guards for /v1/recommendations and /v1/listings/{id}/similar

- 2026-10-15 Candidate pools cached per (adapter, kind, query shape) and reference details per listing id (incl. "not found"), TTL `FF_SOURCING_RECO_CACHE_TTL_S` (60 s); whole responses cached 30 s (`..._RESPONSE_TTL_S`); all three are size-capped LRUs (`..._RECO_CACHE_MAX`, 256). TTL 0 disables. Keys hold public inputs only, so nothing can leak between callers; cached objects are copied before enrichment. Failed/degraded pool results are never cached; neither are partial responses.
- Pool/detail provider calls of these two endpoints go through one `asyncio.Semaphore` (`FF_SOURCING_PROVIDER_CONCURRENCY`, 6).
- Per-request budget `FF_SOURCING_RECO_BUDGET_S` (5 s): unfinished lookups are cancelled and the response carries an additive optional `warning` ("partial_results: ..."); trust-enrichment overrun scores without trust. `/similar` whose reference lookup times out answers 503 `upstream_timeout` (not a false 404).
- Response cache key keeps the caller's ref ORDER (de-duplicated) rather than sorting: order sets recency weights, so a sorted key would serve a different ranking. Pool/detail caches still absorb permutation abuse.
- Native (live) listings: any native create/update/publish clears all three caches (`invalidate_reco`); other changes (e.g. moderation takedown) show up within the TTL at most.
- `/similar` still enriches and records a price observation for the reference on a miss; on a 30 s response-cache hit it does not (the store dedupes within 6 h anyway).
- Scoring: token sets (`Features.all_tokens`) and features are computed once per candidate and reused by both scoring passes; only the 300 capped candidates are featurised.
