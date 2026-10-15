# feed (port 8113)

Social side of the app: supplier/factory **posts**, **follow** / unfollow, a personalized **home feed** (followed suppliers newest first, falling back to trending), **trending**, **likes**, flat **comments**, **reports** with automatic hiding, and admin moderation. Contract: `contracts/openapi/feed.yaml`. Reached through the gateway at `/v1/feed/*` (the admin routes under `/v1/admin/feed/*` are reached through the gateway's allow-listed admin passthrough: `X-Admin-Token` = `FF_GATEWAY_ADMIN_TOKEN`, and the gateway injects `FF_FEED_ADMIN_TOKEN`; 404 when either is unset).

- Identity: `X-User-Id` (required, except anonymous `GET /v1/feed/trending`); posting needs the gateway-verified `X-Supplier-Id` (403 `supplier_required` otherwise). Neither is ever read from a body.
- Posts: text 1-2000 chars, <= 5 media URLs that must be media-service paths (`/v1/media/files/<32 hex>.<jpg|png|webp>`; absolute only under `FF_FEED_MEDIA_BASE_URL`), <= 5 tags, optional `listing_ref` (not verified against sourcing).
- Screening (`moderation.py`, a trimmed copy of sourcing's): links, e-mails, phone numbers, messaging handles and prohibited goods (ar + en) are rejected with 422 `content_rejected`; the match is never echoed.
- Anti-spam (`antispam.py`, pure and deterministic): same-author exact/near duplicate (last 20 posts or comments; normalized hash or 3-word-shingle Jaccard >= 0.9) -> 409 `duplicate_content`; near duplicate of another author's item (24h, Jaccard >= 0.8), per-author velocity (5 posts / 10 comments per 60 s) or obfuscated contact/solicitation/flooding -> 201 with `status: needs_review` (hidden from public surfaces, visible to its author, listed in the admin queue; admin restore publishes). Plain contact info is still rejected by screening (422). See `docs/decisions/feed-antispam.md`.
- Feeds use opaque keyset cursors (`limit` <= 50). Trending = likes + 2 x comments over the last 14 days.
- Reports: N distinct reporters (default 3) hide a post/comment; repeats are accepted silently (202). Admin hide/restore (restore clears the reports).
- Limits: per-user rolling-hour rate limits stored in the DB (so they hold across replicas), plus caps on posts per supplier, follows per user and comments per post.
- Admin: `X-Admin-Token` = `FF_FEED_ADMIN_TOKEN`; 404 when unset.
- Guards: `FF_INTERNAL_TOKEN` (every route except `/health`, `/ready`); `FF_ENV=production` refuses to start without it.

Run: `uvicorn ff_feed.main:app --port 8113` (from `src/`). Test: `../../.venv/bin/python -m pytest`. Migrations: `alembic upgrade head` (SQLite tables are auto-created in dev; PostgreSQL needs the `pg` extra and Alembic).

Env (prefix `FF_FEED_`): `DATABASE_URL`, `DB_AUTO_CREATE`, `ADMIN_TOKEN`, `MEDIA_BASE_URL` (also read from `FF_MEDIA_PUBLIC_BASE_URL`), `REPORT_HIDE_THRESHOLD` (3), `MAX_POSTS_PER_SUPPLIER` (500), `MAX_FOLLOWS_PER_USER` (500), `MAX_COMMENTS_PER_POST` (1000), `MAX_PAGE_SIZE` (50), `TRENDING_WINDOW_DAYS` (14), `RATE_WINDOW_SECONDS` (3600), `RATE_POSTS` (10), `RATE_COMMENTS` (30), `RATE_LIKES` (200), `RATE_FOLLOWS` (60), `RATE_REPORTS` (20) (0 disables a limit); shared `FF_INTERNAL_TOKEN`, `FF_ENV`, `FF_LOG_FORMAT`.

## Ops
`GET /ready` (unauthenticated): 503 when the database is unreachable. One JSON log line per request (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or bodies. `X-Request-Id` is accepted or generated and echoed. Code: `obs.py` (self-contained copy).

## Environment reference (complete)
Every setting in `src/ff_feed/config.py` (`Settings`, case-insensitive env names; empty values count as unset). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_FEED_DATABASE_URL` | sqlite+aiosqlite:///./feed.db |
| `FF_FEED_DB_AUTO_CREATE` | unset |
| `FF_INTERNAL_TOKEN` / `FF_FEED_INTERNAL_TOKEN` | unset |
| `FF_FEED_ADMIN_TOKEN` | unset |
| `FF_FEED_MEDIA_BASE_URL` / `FF_MEDIA_PUBLIC_BASE_URL` | unset |
| `FF_FEED_REPORT_HIDE_THRESHOLD` | 3 |
| `FF_FEED_REPORT_MIN_ACCOUNT_AGE_SECONDS` | 86400 |
| `FF_FEED_MAX_POSTS_PER_SUPPLIER` | 500 |
| `FF_FEED_MAX_FOLLOWS_PER_USER` | 500 |
| `FF_FEED_MAX_COMMENTS_PER_POST` | 1000 |
| `FF_FEED_MAX_PAGE_SIZE` | 50 |
| `FF_FEED_DEFAULT_PAGE_SIZE` | 20 |
| `FF_FEED_TRENDING_WINDOW_DAYS` | 14 |
| `FF_FEED_RATE_WINDOW_SECONDS` | 3600 |
| `FF_FEED_RATE_POSTS` | 10 |
| `FF_FEED_RATE_COMMENTS` | 30 |
| `FF_FEED_RATE_LIKES` | 200 |
| `FF_FEED_RATE_FOLLOWS` | 60 |
| `FF_FEED_RATE_REPORTS` | 20 |
| `FF_FEED_ANTISPAM_AUTHOR_HISTORY` | 20 (0 disables the same-author check) |
| `FF_FEED_ANTISPAM_AUTHOR_SIMILARITY` | 0.9 (0 = exact normalized match only) |
| `FF_FEED_ANTISPAM_CROSS_WINDOW_HOURS` | 24 (0 disables the cross-author check) |
| `FF_FEED_ANTISPAM_CROSS_SIMILARITY` | 0.8 (0 = exact only) |
| `FF_FEED_ANTISPAM_CROSS_SCAN_LIMIT` | 500 |
| `FF_FEED_ANTISPAM_MIN_TOKENS` | 4 (shorter texts are never duplicates) |
| `FF_FEED_ANTISPAM_VELOCITY_POSTS` | 5 (0 disables) |
| `FF_FEED_ANTISPAM_VELOCITY_COMMENTS` | 10 (0 disables) |
| `FF_FEED_ANTISPAM_VELOCITY_WINDOW_SECONDS` | 60 |
| `FF_FEED_ANTISPAM_SUSPICIOUS` | 1 (0 disables obfuscation/solicitation/flooding signals) |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default), `FF_ENV=production` refuses to start without `FF_INTERNAL_TOKEN` (see `docs/OPS.md`).
