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

## Environment reference (complete)
Every setting in `src/ff_messaging/config.py` (`Settings`, case-insensitive env names; empty values count as unset). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_MESSAGING_DATABASE_URL` | sqlite+aiosqlite:///./messaging.db |
| `FF_MESSAGING_DATABASE_ECHO` | False |
| `FF_MESSAGING_DB_AUTO_CREATE` | unset |
| `FF_INTERNAL_TOKEN` / `FF_MESSAGING_INTERNAL_TOKEN` | unset |
| `FF_MESSAGING_MAX_TEXT_LENGTH` | 4000 |
| `FF_MESSAGING_MAX_TITLE_LENGTH` | 200 |
| `FF_MESSAGING_PREVIEW_LENGTH` | 120 |
| `FF_MESSAGING_MAX_PARTICIPANTS` | 10 |
| `FF_MESSAGING_MAX_BODY_BYTES` | 65536 |
| `FF_MESSAGING_MAX_EVENT_DATA_BYTES` | 8192 |
| `FF_MESSAGING_ABUSE_FILTER_ENABLED` | True |
| `FF_MESSAGING_ABUSE_ACTION` | flag |
| `FF_MESSAGING_ABUSE_TERMS` | unset |
| `FF_MESSAGING_ABUSE_TERMS_EXTRA` | [] |
| `FF_MESSAGING_CONVERSATION_CREATE_LIMIT` | 10 |
| `FF_MESSAGING_CONVERSATION_CREATE_WINDOW_SECONDS` | 60.0 |
| `FF_MESSAGING_MAX_CONVERSATIONS_PER_USER` | 1000 |
| `FF_MESSAGING_MAX_MESSAGES_PER_CONVERSATION` | 10000 |
| `FF_MESSAGING_SEND_RATE_LIMIT` | 20 |
| `FF_MESSAGING_SEND_RATE_WINDOW_SECONDS` | 10.0 |
| `FF_MESSAGING_ATTACHMENT_MAX_BYTES` | 26214400 |
| `FF_MESSAGING_ATTACHMENT_ALLOWED_MIME_TYPES` | ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'i... |
| `FF_MESSAGING_ATTACHMENT_ALLOWED_HOSTS` | [] |
| `FF_MESSAGING_ATTACHMENT_ALLOW_HTTP` | False |
| `FF_MESSAGING_MEDIA_ALLOWED_HOSTS` | [] |
| `FF_MESSAGING_MEDIA_PATH_PREFIXES` | ['/v1/media/files/'] |
| `FF_MESSAGING_MEDIA_MAX_ATTACHMENTS` | 5 |
| `FF_MESSAGING_PLATFORM_USER_IDS` | ['usr_support'] |
| `FF_MESSAGING_SUPPORT_USER_ID` | usr_support |
| `FF_MESSAGING_MESSAGES_PAGE_SIZE` | 30 |
| `FF_MESSAGING_MESSAGES_PAGE_SIZE_MAX` | 100 |
| `FF_MESSAGING_CONVERSATIONS_PAGE_SIZE` | 20 |
| `FF_MESSAGING_CONVERSATIONS_PAGE_SIZE_MAX` | 100 |
| `FF_MESSAGING_TYPING_TTL_SECONDS` | 6 |
| `FF_MESSAGING_TYPING_THROTTLE_SECONDS` | 2.0 |
| `FF_MESSAGING_WS_ALLOW_QUERY_USER_ID` | unset |
| `FF_MESSAGING_WS_QUEUE_SIZE` | 256 |
| `FF_MESSAGING_WS_MAX_CONNECTIONS_PER_USER` | 20 |
| `FF_MESSAGING_WS_INBOUND_RATE_LIMIT` | 30 |
| `FF_MESSAGING_WS_INBOUND_RATE_WINDOW_SECONDS` | 10.0 |
| `FF_MESSAGING_WS_MAX_FRAME_CHARS` | 8192 |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default), `FF_ENV=production` refuses to start without `FF_INTERNAL_TOKEN` (see `docs/OPS.md`).

Rate limits (send, new-conversation, WebSocket inbound frames) use `ratelimit.py` (self-contained copy of `packages/py-common/src/ff_common/ratelimit.py`). In-memory by default; set `FF_REDIS_URL` (or `FF_MESSAGING_REDIS_URL`; needs `pip install ff-messaging[redis]`) to share counters across replicas. Redis outage falls back to per-process counting with a warning. On Redis the sliding window degrades to a fixed window. WebSocket flood: frames beyond `WS_INBOUND_RATE_LIMIT` per `WS_INBOUND_RATE_WINDOW_SECONDS` get an `error`/`rate_limited` frame and are dropped.
