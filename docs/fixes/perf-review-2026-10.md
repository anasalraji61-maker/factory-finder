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

## Open
- logistics landed-cost quote is 8-40x slower than other paths: profile first.
- rfq `list_requests`: one count query per row (N+1) -> single GROUP BY.
- rfq `_sweep` writes on reads.
- notifications unbounded reads: list_watches, list_deliveries, owners_with_email_prefs, mark_alerts_read.
- gateway admin supplier-claims has no limit.
- JSON blob columns (demand doc, rfq attachments/destination, messaging) need write-time caps.
