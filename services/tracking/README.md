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


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).
