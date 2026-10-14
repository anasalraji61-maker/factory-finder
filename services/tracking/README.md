# tracking (port 8107)

Track shipments by container (ISO 6346), bill of lading, air waybill (mod-7) or vessel IMO.
Normalized statuses (booked ... delivered), bilingual event timeline, progress %, per-user ownership.

- Run: `uvicorn ff_tracking.main:app --port 8107`; tests: `../../.venv/bin/python -m pytest -q`
- Contract: `contracts/openapi/tracking.yaml`. Auth: `X-User-Id` (missing -> 401); `X-Internal-Token` checked only if `FF_INTERNAL_TOKEN` is set.
- Providers (`adapters/`): `mock` (default, deterministic timeline that progresses with time) and a licensed-provider stub. No scraping of carrier sites.
- Refresh is throttled: too soon -> 429 `refresh_throttled` with `Retry-After`.

| Env | Default |
|---|---|
| `FF_TRACKING_DATABASE_URL` | `sqlite+aiosqlite:///./tracking.db` |
| `FF_TRACKING_PROVIDER` | `mock` |
| `FF_TRACKING_PROVIDER_API_KEY` | empty |
| `FF_TRACKING_REFRESH_MIN_INTERVAL_SECONDS` | `60` |


## Real providers (Phase 4 prep, OFF by default)
`FF_TRACKING_PROVIDER=http` routes container/B-L to `HttpContainerProvider`, AWB to `HttpAwbProvider`, vessel IMO to
`HttpVesselPositionProvider` (AIS, position + ETA only, official API only). **All wire shapes are UNVERIFIED** and
fixture-driven (`tests/fixtures`); re-check against the licensed provider's docs before enabling. Carrier is detected from
the container owner code (SCAC table, 23 lines) / AWB prefix (57 airlines).
- Normalization (`domain/normalize.py`): status mapping table (ocean codes + IATA Cargo-IMP), UTC timestamps, UN/LOCODE/IATA
  location resolution, dedupe + ordering, milestones (gate_in, loaded, departed, transshipment, arrived, discharged, gate_out,
  delivered), ETA/delay flag (`delayed`, `delay_hours`, `initial_eta`; stale past ETA recomputed to now+24 h).
- Safety: >= 3 s per host, response cache, honest User-Agent, cooldown after errors, no retries/bypass. Kill switch:
  `FF_TRACKING_KILL_SWITCH=1` (or `FF_TRACKING_CONTAINER_DISABLED` / `_AWB_DISABLED` / `_VESSEL_DISABLED`). On any failure
  the answer degrades to the mock with `warning` (`provider_unavailable:<reason>`); real events already held are never
  overwritten by mock data. `FF_TRACKING_FALLBACK_TO_MOCK=false` returns 502 instead.
- Background refresh (`jobs.py`, `FF_TRACKING_REFRESH_JOB_ENABLED=true`): refreshes non-delivered shipments at most every
  `FF_TRACKING_REFRESH_JOB_INTERVAL_HOURS` (default 6) and writes `tracking_outbox` rows (`status_changed`,
  `shipment_delayed`; unique `dedupe_key` => once per change). Notifications integration: `docs/requests/tracking-notify.md`.

| Extra env | Default |
|---|---|
| `FF_TRACKING_{CONTAINER,AWB,VESSEL}_BASE_URL` / `_API_KEY` | empty (env only, never logged) |
| `FF_TRACKING_HTTP_MIN_INTERVAL_SECONDS` / `_HTTP_CACHE_TTL_SECONDS` | `3` / `3600` |
| `FF_TRACKING_FALLBACK_TO_MOCK` | `true` |
| `FF_TRACKING_REFRESH_JOB_{ENABLED,INTERVAL_HOURS,POLL_SECONDS,BATCH_SIZE}` | `false` / `6` / `600` / `50` |

## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

## Notifications relay (`relay.py`, OFF by default)
`FF_TRACKING_NOTIFY_RELAY=on` + `FF_TRACKING_NOTIFY_BASE_URL` starts a loop that POSTs undelivered `tracking_outbox` rows (id order,
batches <= 100) to notifications `POST /v1/internal/tracking-events` with `X-Internal-Token` (`FF_INTERNAL_TOKEN`). `created`/`duplicate`
-> `delivered_at`; `invalid` -> dead at once (kept, `last_error`); batch failure / missing result -> `attempts+1`, exponential backoff
(`next_attempt_at`), dead after max attempts. HTTP sits behind `NotifyClient` (`HttpNotifyClient`, `MockNotifyClient` for tests).
Migration `0003` adds `attempts, next_attempt_at, dead_at, last_error`. Status: `GET /v1/internal/outbox-status` (counters).

| Env | Default |
|---|---|
| `FF_TRACKING_NOTIFY_RELAY` | `off` |
| `FF_TRACKING_NOTIFY_BASE_URL` | empty (relay stays off with a warning) |
| `FF_TRACKING_NOTIFY_{BATCH_SIZE,MAX_ATTEMPTS}` | `100` / `8` |
| `FF_TRACKING_NOTIFY_BACKOFF_{BASE,MAX}_SECONDS` | `30` / `3600` |
| `FF_TRACKING_NOTIFY_{POLL,TIMEOUT}_SECONDS` | `30` / `10` |
