# Performance

All numbers measured in this sandbox (mock data, services as separate local processes), not production figures.

## End-to-end (`python scripts/bench.py`, n=50, gateway -> service hops included)

| path | before p50 / p95 ms | after p50 / p95 ms |
|---|---|---|
| search (en) | 17.8 / 26.3 | 16.6 / 26.3 |
| search (ar, price_asc) | 20.0 / 33.3 | 18.9 / 29.7 |
| landed-cost quote | 11.0 / 14.7 | 9.8 / 13.9 |
| trust score | 4.5 / 5.8 | 3.9 / 5.1 |
| listing detail | 4.6 / 6.1 | 3.6 / 4.4 |

Run-to-run noise is about +-1 ms; the end-to-end differences are mostly noise. The gains are in the micro-benchmarks below.

## Geo micro-benchmarks (in-process, 174 sea nodes, 249 edges, 452 cities)

| operation | before p50 | after p50 |
|---|---|---|
| sea Shanghai -> Hamburg (warm) | 1.010 ms | 0.006 ms |
| sea, avoid=suez (warm) | 0.401 ms | 0.005 ms |
| sea, cold (cache cleared) | ~1.0 ms | ~0.78 ms |
| `GET /v1/cities?q=sh` search logic | 2.203 ms | 0.332 ms |

## Changes
- geo `sea._dijkstra`: result cache (`lru_cache`, 4096 entries) and a predecessor map instead of copying a path list per heap push; `_access` cached (2048 entries, tuple result).
- geo `search_cities`: normalised names precomputed once per dataset instead of per query.
- sourcing `rank`: price-fit position via a precomputed table (was `list.index`, O(n^2) per category group).

## Reviewed, no change needed
- logistics: `CachedGeo` (TTL + size bounded) plus per-request `Engine.dist` cache already remove repeated geo hops.
- sourcing: search results, trust and token lookups are TTL/LRU bounded; adapters run concurrently with timeouts.
- gateway: active-user cache (5 s, 10k cap) and the rate limiter are bounded; no blocking calls in async handlers.

## Open observations (not changed)
- gateway `RateLimiter._make_room` rebuilds the whole table on every new key once at `max_keys` with all keys live (O(n) per hit under a key flood).
- gateway proxy does up to 2 separate user-row queries per request for rfq/messaging/feed (active check plus supplier claim); could be merged.
- logistics `CachedGeo` has no in-flight de-duplication for concurrent identical misses.


## Update 2026-10-15
Gateway `RateLimiter._make_room` is now amortized (expired prefix pop + 1% batch eviction) and the proxy loads the user row at most once per request. `CachedGeo` in-flight de-duplication remains open.


## Update 2026-10-15: DB hot paths (feed, rfq, tracking, trust, sourcing)
In-process, SQLite in memory, seeded 5k and 50k rows, best of 3, no network (scripts were throwaway; the regression tests below pin the behaviour). Absolute numbers are SQLite on one core; the query counts and plans are what carry over to PostgreSQL.

| path (50k rows unless noted) | before | after |
|---|---|---|
| feed `GET /trending` first page | 275 ms (skewed likes) / 549 ms (uniform), 2 queries, ranks every post in the 7-day window | 44 ms, 4 queries, ranks only top-score candidates |
| feed `GET /home` (followed suppliers), supplier posts, admin posts | 1.5-4 ms | unchanged (already index-driven) |
| rfq lazy sweep with a 13k-request expiry backlog | 6010 ms, 5445 queries | 468 ms, 31 queries (constant per 500 touched requests) |
| rfq sweep, 5k rows | 538 ms, 576 queries | 44 ms, 9 queries |
| rfq `GET /requests?scope=mine` (20 owned rows) | 18.4 ms, 23 queries | 6.1 ms, 4 queries |
| tracking refresh job, one cycle | 1563 ms (loads and parses all 45k active shipments) | 6.3 ms (one indexed query, batch of 50) |
| trust `suppliers:batch` 50 ids, cold | 341 ms, 303 queries | 44-62 ms, 9 queries |
| trust report submit x50 (50k reports) | 555 ms | 307 ms (low-trust count now index-only) |
| sourcing native search (200 rows, 2 ms supplier lookup) | 487 ms | 83 ms |
| sourcing `NativeStore.published(200)` | 29.9 ms | 8.3 ms |

### Changes
- feed `trending`: `posts.score` (external likes + 2 x external comments, kept on write) is an upper bound of the exact snapshot engagement, so the exact rank (the two correlated COUNT subqueries) is computed only for the top-K scored posts (`ix_posts_status_score`, no sort), K widening x4 until no unseen post can beat the page (`score + FRESH_BOOST` < k-th rank). Result is identical to the full ranking (test compares against a brute-force ranking over 4 pages). Ordering of the candidates is done in Python because an SQL ORDER BY on the correlated rank re-evaluates the subqueries.
- rfq `_sweep`: set-based UPDATEs instead of loading and mutating every lapsed row and then `get` + COUNT per touched request. `list_requests(scope=mine)` loads invites for all rows in one query (was one per row). Migration 0007: `ix_requests_status_deadline`, `ix_offers_status_valid_until`, `ix_offers_request_status`, `ix_reviews_supplier_status_created`, `ix_reviews_supplier_status_rating` (supplier review lists were sorting every review of the supplier).
- tracking: new `shipments.refresh_marker` (last attempt/refresh; epoch = never refreshed, year 9999 = delivered; backfilled by migration 0004 from the JSON) plus `ix_shipments_refresh` and `ix_shipments_owner_created`; `RefreshJob` uses `ShipmentRepository.due_for_refresh(cutoff, batch)` instead of `active()` (kept for compatibility).
- trust: `TrustService.for_suppliers` (used by `suppliers:batch`) shares one accepted-report query, one verification-evidence query and one snapshot transaction (`SnapshotStore.add_many`, window function for the latest row per supplier). Migration 0004: `ix_reports_lowtrust_status_created`.
- sourcing: native search resolves each distinct supplier concurrently (bounded 8) instead of sequentially; `kind`/`condition` filters are pushed into the published-window query; migration 0006: `ix_native_listings_status_published`, `ix_native_listings_status_kind_published`.
- Regression tests (`tests/test_perf_queries.py` in each service) assert query counts via SQLAlchemy `before_cursor_execute` counters and `EXPLAIN QUERY PLAN` index use.

### Open observations (not changed)
- rfq `list_requests(scope=market)`: `status IN (open, negotiating)` + `ORDER BY created_at` still sorts the live set (about 40-58 ms at 50k) and the total COUNT scans it; fixing needs per-status merged index scans or keyset pagination (contract change).
- feed trending deep pages (cursor far down) widen the candidate pool towards the whole window, so page N costs up to the old full scan; the first pages (the hot case) are bounded. A `home` feed for a user who follows only rarely-posting suppliers scans `ix_posts_status_created` newest-first until it finds a page.
- trust `ReportStore.add` still runs about 7 statements per report (rate window, two counts, insert, purge check); fine at current volume.
- Trending relies on `posts.score` never being lower than the exact external engagement; any new write path that changes likes/comments must keep updating it (existing `_recount`, like/unlike do).


## Load test 2026-10-16 (`make load-test` / `python scripts/load_test.py`)
Mixed workload through the gateway: 50 synthetic users (registered up front), 60 s, 30 concurrent workers, weights search 30 / landed-cost 15 / feed home 15 / rfq list 12 / tracking list 10 / assistant 10 / rfq create 8. The script starts the stack like `scripts/e2e.py` (so run it ALONE), exits 1 on any 5xx / transport error or any endpoint p95 > 2 s. Raising `FF_GATEWAY_REGISTER_PER_HOUR` is the only extra setting (the per-IP signup cap of 10/h would reject the users).

**Caveat:** numbers are for mock adapters, SQLite, one uvicorn process per service, on a 2-core sandbox shared by 15 services plus the load generator. They show relative hot spots and the absence of errors, not production capacity.

| endpoint | n | req/s | p50 ms | p95 ms | p99 ms | 5xx | 4xx |
|---|---|---|---|---|---|---|---|
| search | 687 | 11.4 | 805 | 2037 | 4598 | 0 | 0 |
| landed-cost | 290 | 4.8 | 349 | 751 | 1368 | 0 | 0 |
| feed home | 355 | 5.9 | 722 | 1242 | 1435 | 0 | 0 |
| rfq create | 187 | 3.1 | 696 | 1115 | 1244 | 0 | 0 |
| rfq list (mine) | 252 | 4.2 | 738 | 1099 | 1444 | 0 | 0 |
| tracking list | 228 | 3.8 | 344 | 1007 | 1315 | 0 | 0 |
| assistant query | 220 | 3.6 | 1434 | 3268 | 7748 | 0 | 0 |
| total | 2219 | 36.7 | | | | 0 | 0 |

Result: zero 5xx and zero 4xx; the run FAILS the p95 gate on `search` (2037 ms, marginal) and `assistant` (3268 ms). The box is CPU-saturated at concurrency 30 (every endpoint's p50 rises 5-10x versus concurrency 5: tracking list 45 ms -> 344 ms), so most of the latency is queueing. Findings from a single-client probe: sequential warm search costs 200-600 ms on its own (a broad query like "machine" returns a 21 KB body in ~600 ms) and the first, cold request per query is 1.1-4.7 s; the assistant calls sourcing search plus a landed-cost quote, so it inherits that. Search is the lever to pull next (CPU per request in sourcing ranking / trust enrichment / gateway serialization), not a correctness bug. No service code was changed.
