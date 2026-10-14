# Performance review — 2026-10 (mock data, local processes, 50 iterations)

| Path | p50 ms | p95 ms |
|---|---|---|
| search (en) | 17.2 | 25.0 |
| search (ar, price_asc) | 21.1 | 26.9 |
| landed-cost quote | 147.5 | 192.4 |
| trust score | 3.8 | 5.4 |
| listing detail | 4.4 | 8.8 |
| requests list | 13.2 | 16.5 |
| notifications inbox | 6.9 | 9.5 |

Run `python scripts/bench.py` (informational, exit 0).

## Fixed
- rfq: composite indexes on requests (owner/status + created_at), deals (buyer/supplier + created_at).
- demand: capped list_signals / list_drafts.
- logistics landed-cost quote 143 -> 7.8 ms p50 (p95 166 -> 9.8). cProfile (`scripts/profile_quote.py`): engine compute is only ~2.4 ms; the rest was ~47 sequential HTTP calls to geo per quote (same hubs/nearest/distance lookups repeated per mode x hub pair). Added `CachedGeo` (TTL 600 s, bounded, errors never cached; `FF_LOGISTICS_GEO_CACHE_TTL_SECONDS`), origin/destination resolved concurrently, `load_json` memoised. Outputs unchanged (golden tests identical).
- rfq `list_requests`: N+1 replaced with one GROUP BY count.
- rfq `_sweep`: throttled; the two SELECTs only run when something is due (earliest deadline/valid_until tracked), after a local write that adds a deadline, or after 30 s (covers other processes).
- notifications: list_watches / list_deliveries / owners_with_email_prefs capped (default 100, max 500) with offset/keyset paging; evaluate_all and digests iterate in batches; `GET /v1/watchlist` accepts limit (<=200, default 100) and offset; `mark_alerts_read` is one UPDATE (SQLite json_patch; PostgreSQL jsonb merge, not exercised here).
- gateway admin supplier-claims: `page` + `limit` (default 50, max 200), response adds total/page/page_size.

## Open
- JSON blob columns (demand doc, rfq attachments/destination, messaging) need write-time caps.
- notifications `mark_alerts_read` PostgreSQL branch is untested (no PG in CI).
- logistics: first (cold-cache) quote still makes the geo hops sequentially; consider batching or a bulk geo endpoint if cold latency matters.
