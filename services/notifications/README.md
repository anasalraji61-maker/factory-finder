# notifications (port 8108)

Watchlist (listing or saved search + optional target price), rule evaluation against sourcing, alerts inbox, device tokens and push. Contract: `contracts/openapi/notifications.yaml`.

- Rules (`domain/rules.py`): `price_drop` (>= threshold % below the last reported price), `below_target`, `cheaper_equivalent` (other supplier, same category/condition/unit, not red trust), plus `back_in_stock` and `new_results`. Bilingual alert text (ar/en).
- Admission (`domain/policy.py`): per (watch, rule) cooldown (default 24h) and dedupe of identical events; an event suppressed by cooldown stays pending.
- `POST /v1/alerts/evaluate` (internal) evaluates active watches via `clients/sourcing.py` (httpx; `MockSourcingClient` is scriptable for tests), stores alerts, sends one push summary per owner to their devices (`adapters/push.py`: mock, FCM stub disabled).
- Optional scheduler (`FF_NOTIFICATIONS_SCHEDULER_ENABLED=true`, interval `..._SCHEDULER_INTERVAL_SECONDS`), off by default.

Run: `uvicorn ff_notifications.main:app --port 8108` (from `src/`). Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_NOTIFICATIONS_`): `DATABASE_URL`, `SOURCING_BASE_URL`, `USE_MOCK_SOURCING`, `COOLDOWN_HOURS`, `DEFAULT_DROP_THRESHOLD_PCT`, `PUSH_PROVIDER` (mock|fcm), `FCM_ENABLED`, `SCHEDULER_ENABLED`; shared `FF_INTERNAL_TOKEN`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).
