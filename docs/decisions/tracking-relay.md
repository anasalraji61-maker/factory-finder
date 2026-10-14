2026-10-14 | Relay is a push loop in services/tracking (`relay.py`), off unless FF_TRACKING_NOTIFY_RELAY=on and a base URL is set | matches notifications' push model; replays are idempotent by dedupe_key
2026-10-14 | `invalid` items go dead immediately (not retried), kept with last_error | retrying a malformed event cannot succeed; request said leave for inspection
2026-10-14 | Outbox gets attempts/next_attempt_at/dead_at/last_error (migration 0003); backoff base*2^(n-1) capped, dead after 8 attempts | bounded retries, no poison-row blocking since due rows are filtered
2026-10-14 | Added `GET /v1/internal/outbox-status` (additive contract) | cheap ops visibility, guarded by the internal token
