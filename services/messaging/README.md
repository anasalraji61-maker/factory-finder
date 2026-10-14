# messaging (port 8106)

Conversations between buyers and suppliers (context: listing / request / deal / support), messages (text, attachment URL, offer reference), unread counts, read receipts, cursor pagination, WebSocket fan-out. Contract: `contracts/openapi/messaging.yaml`.

- Auth: `X-User-Id` (and `X-Internal-Token` when `FF_INTERNAL_TOKEN` is set). Participants only (403 otherwise).
- Create is idempotent per (participant set, context). `client_message_id` makes sends idempotent.
- Safety: abuse word list (flag by default, or mask/reject), length cap, attachment URL/MIME checks, per-user send rate limit (429 + Retry-After).
- WebSocket `/v1/ws/conversations/{id}?user_id=` (query user id only when no internal token is set): events `message.created`, `read.updated`, `typing`; in-process hub (single instance).

Run: `uvicorn ff_messaging.main:app --port 8106` (from `src/`). Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_MESSAGING_`): `DATABASE_URL`, `MAX_TEXT_LENGTH`, `ABUSE_ACTION` (flag|mask|reject), `ABUSE_TERMS_EXTRA`, `SEND_RATE_LIMIT`, `SEND_RATE_WINDOW_SECONDS`, `ATTACHMENT_ALLOWED_HOSTS`, `PLATFORM_USER_IDS`, ... see `config.py`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).
