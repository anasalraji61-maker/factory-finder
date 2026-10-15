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
