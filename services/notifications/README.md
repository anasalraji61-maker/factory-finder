# notifications (port 8108)

Watchlist (listing or saved search + optional target price), rule evaluation against sourcing, alerts inbox, device tokens and push. Contract: `contracts/openapi/notifications.yaml`.

- Rules (`domain/rules.py`): `price_drop` (>= threshold % below the last reported price), `below_target`, `cheaper_equivalent` (other supplier, same category/condition/unit, not red trust), plus `back_in_stock` and `new_results`. Bilingual alert text (ar/en).
- Admission (`domain/policy.py`): per (watch, rule) cooldown (default 24h) and dedupe of identical events; an event suppressed by cooldown stays pending.
- `POST /v1/alerts/evaluate` (internal) evaluates active watches via `clients/sourcing.py` (httpx; `MockSourcingClient` is scriptable for tests), stores alerts, then enqueues deliveries (see below).
- Optional scheduler (`FF_NOTIFICATIONS_SCHEDULER_ENABLED=true`, interval `..._SCHEDULER_INTERVAL_SECONDS`), off by default.

Run: `uvicorn ff_notifications.main:app --port 8108` (from `src/`). Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_NOTIFICATIONS_`): `DATABASE_URL`, `SOURCING_BASE_URL`, `USE_MOCK_SOURCING`, `COOLDOWN_HOURS`, `DEFAULT_DROP_THRESHOLD_PCT`, `SCHEDULER_ENABLED`; shared `FF_INTERNAL_TOKEN`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).


## Delivery (push / email digest) — all off by default
- Devices: `POST/GET /v1/devices`, `DELETE /v1/devices/{id}`; max 10 active per user (422 `device_limit`), deduped by token, token never logged. Provider-reported invalid tokens deactivate the device (`active:false`); re-registering reactivates it.
- Prefs: `GET/PUT /v1/notification-prefs` — channels per alert type (`in_app|push|email`), quiet hours (`HH:MM`, wraps midnight) in the user's IANA timezone (default Asia/Baghdad), language `ar|en` (else per-device locale), digest `email`. Re-read at send time. Quiet hours defer push to the window end (not an attempt). `in_app` never suppresses the inbox.
- Pipeline (`delivery.py`): alerts commit first; `deliveries` rows have deterministic ids (idempotent), retry with exponential backoff (`DELIVERY_BACKOFF_BASE_SECONDS`/`_MAX_SECONDS`) up to `DELIVERY_MAX_ATTEMPTS`, then status `dead`. Processed right after evaluation and by the scheduler; failures never affect alert creation.
- Providers: `FF_NOTIFY_PUSH=off|mock|fcm` (`MockPush`; `FcmPush` = FCM HTTP v1 + service-account JWT via `ServiceAccountTokenProvider`, needs `pip install .[fcm]`; UNVERIFIED against live FCM). `FF_NOTIFY_EMAIL=off|mock|smtp` (`MockEmail`; `SmtpEmail` skeleton, UNVERIFIED). FCM creds: `FF_NOTIFY_FCM_PROJECT_ID` + `FF_NOTIFY_FCM_CREDENTIALS_FILE` or `_JSON`; SMTP: `FF_NOTIFY_SMTP_HOST/PORT/USER/PASSWORD/FROM`.
- Digest: `POST /v1/alerts/digest` (internal; also run by the scheduler) mails alerts of the last 24h where the user enabled `email`, after 08:00 local, once per local day.
