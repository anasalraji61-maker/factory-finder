# messaging (port 8106)

Conversations between buyers and suppliers (context: listing / request / deal / support), messages (text, attachment URL, offer reference), unread counts, read receipts, cursor pagination, WebSocket fan-out. Contract: `contracts/openapi/messaging.yaml`.

- Auth: `X-User-Id` (and `X-Internal-Token` when `FF_INTERNAL_TOKEN` is set). Participants only (403 otherwise).
- Create is idempotent per (participant set, context). `client_message_id` makes sends idempotent.
- Safety: abuse word list (flag by default, or mask/reject), length cap, attachment URL/MIME checks, per-user send rate limit (429 + Retry-After).
- WebSocket `/v1/ws/conversations/{id}?user_id=` (query user id only when no internal token is set): events `message.created`, `read.updated`, `typing`; in-process hub (single instance).

Media attachments: optional `attachments[]` on text/attachment messages (max 5): `{url, kind: image|document, size?, name?}`. Messaging stores references only (no bytes); `url` must be a media-service URL: path under `FF_MESSAGING_MEDIA_PATH_PREFIXES` (default `/v1/media/files/`, file name `<id>.<ext>`, only `?w=NNN` query), absolute URLs also need a host in `FF_MESSAGING_MEDIA_ALLOWED_HOSTS` (empty = any host; https only unless `ATTACHMENT_ALLOW_HTTP`). Attachment-only messages need no text; conversation preview is `[image]` / `[document]` / `[attachment]` (language-neutral keys the clients localise). Not combinable with legacy single `attachment`. Migration `0002` adds `messages.attachments`. Env: `MEDIA_ALLOWED_HOSTS`, `MEDIA_PATH_PREFIXES`, `MEDIA_MAX_ATTACHMENTS`.

Run: `uvicorn ff_messaging.main:app --port 8106` (from `src/`). Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_MESSAGING_`): `DATABASE_URL`, `MAX_TEXT_LENGTH`, `ABUSE_ACTION` (flag|mask|reject), `ABUSE_TERMS_EXTRA`, `SEND_RATE_LIMIT`, `SEND_RATE_WINDOW_SECONDS`, `ATTACHMENT_ALLOWED_HOSTS`, `PLATFORM_USER_IDS`, ... see `config.py`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

Caps env: `FF_MESSAGING_MAX_CONVERSATIONS_PER_USER` (1000), `FF_MESSAGING_MAX_MESSAGES_PER_CONVERSATION` (10000); 0 = unlimited. Erasure blanks the erased user's message text.
