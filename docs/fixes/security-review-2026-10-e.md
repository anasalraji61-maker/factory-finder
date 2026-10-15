# Security review 2026-10-e (account deletion/export, supplier analytics, price history/recommendations, private media, trust persistence, gateway paths, serve_stack, CI)

## Fixed in place
- **Gateway path normalisation** (`api/proxy.py`): besides `.`/`..` now also refuses empty segments (`//`), backslashes and still-encoded
  `%2e` / `%2f` / `%5c` (a double-encoded `%252e` decodes to `%2e` at the gateway and to `.` at an upstream or fronting proxy). Policy
  checks (internal-only, verified-email, supplier-claim) run on the decoded path, so anything normalised differently downstream is refused (400).
  Test: `gateway/tests/test_security_review.py::test_path_tricks_are_refused`.
- **Trailing-newline regex slips**: `$` matches before a final `\n`. Switched to `\Z` in gateway routing (`TRUST_BADGE_PATH`, `LISTING_EVENTS_PATH`,
  `RFQ_SUPPLIER_PATH`), admin allow-lists (`admin_services`, `admin_payments`, `admin_media`) and sourcing (`events` listing/user id, `ref` ids).
  Test: sourcing `test_newline_in_listing_id_is_rejected`.
- **Media signed URL 500**: `exp=%C2%B2` (superscript two) passes `str.isdigit()` but `int()` raises -> unauthenticated 500 on a public route. Now `isascii()` too.
  Test added to `media/tests/test_private.py::test_tampered_signatures`.
- **Payments export leaked the payer's memo to the payee**: the export lists invoices where the user is payer OR payee, including `user_memo`
  (typed by the payer). Memo is now only returned to the payer; `payer_user_id` is not exposed. Test in `payments/tests/test_privacy.py`.
- **Analytics viewer key**: an IPv6 client owns a whole /64, so rotating addresses defeated the per-IP rate limit and the dedupe window
  (inflating a competitor's or one's own view counts). The sourcing event handler now keys on the /64 (IPv4-mapped -> IPv4). Tests in `sourcing/tests/test_analytics.py`.
- **serve_stack / e2e guard**: `e2e.start_services` (used by e2e, e2e_extended and serve_stack) now exits when `FF_ENV` is production/prod/staging/stage
  (or `FF_PRODUCTION` is set): these harnesses use well-known tokens and unset the internal token. serve_stack also writes its info file (test
  credentials) with mode 0600. Services bind 127.0.0.1 (uvicorn default).
- **CI**: `backend`, `e2e`, `mobile`, `mobile-live` had no `permissions:` (default token may be read/write on push); all now `contents: read`.
  Verified: no `pull_request_target`, no `secrets.*`, `workflow_dispatch` inputs reach shell only through `env:` (no `${{ }}` inside `run:`).

## Verified OK (no change)
- Account deletion/export: user id is `quote(safe='')`-encoded into the path; every service's `/v1/internal/users/*` is token-guarded and answers 404
  to non-internal callers (feed/freight/demand/notifications/messaging/rfq via guard, others via middleware); re-auth is required for the first
  DELETE; throttled 3/min per user; export is capped per service and in total, secrets/hashes never included (devices masked, verification
  tokens replaced by a status, `password_hash` not in the profile); tombstones are per-service salted hashes; sourcing only gets the *verified* supplier id
  (gateway-set, `supplier_id` is unique per user so no cross-user over-deletion).
- Private media: random 128-bit ids, `p-` storage keys unreachable from the public route, sniffed JPEG/PNG/WebP only and re-encoded (no SVG/HTML stored),
  fixed content types, nosniff + `default-src 'none'`, HMAC bound to id+owner+exp, constant-time compare, 5 min TTL with +5 s skew cap, production requires the signing key.
- Trust persistence: all SQL is bound parameters (the only `text()` calls are constants / `pg_advisory_xact_lock(hashtext(:k))`); audit table
  append-only by trigger on SQLite and PostgreSQL (also created in migration 0001); check-then-write sections serialised (SQLite `BEGIN IMMEDIATE`, PG advisory lock);
  duplicate guard is a partial unique index.
- Freight accept: revision check plus CAS on `(status=submitted, revision)`; feed/freight cursors 422 on hostile input; recommendations `ref` capped (20 ids, 64 chars, 1500 total).
- Analytics: nothing persisted per viewer; every in-memory structure is bounded and wiped at UTC midnight; non-published/unknown ids answer the same 202 `counted:false`;
  `X-Client-Ip` is only forwarded by the gateway for the events route, computed from the trusted-proxy chain (never from client headers), and sourcing rejects `/events` without the internal token when one is configured.

## Open (design / needs product decision)
1. MEDIUM - **Recommendations / similar are an amplification endpoint** - FIXED 2026-10-15 (docs/decisions/sourcing-reco-cache.md): TTL-cached pools/details/responses, provider semaphore, time budget with partial+warning, cheaper scoring. Original finding: (public, anonymous): one request fans out up to 20 `get_listing` calls plus a
   pool query of up to 200 items per adapter per kind, then scores pool x refs (~10k similarity evaluations on the event loop), with no cache. Needs a short TTL
   cache for the pool (keyed by kind set) and for `get_listing` by id, plus a semaphore around licensed-provider calls. Not done here: caching changes freshness semantics tests rely on.
2. LOW - Freight accept's `revision` is optional; a client that omits it keeps the bait-and-switch window. Make the mobile app always send it, then require it in `/v2`.
3. LOW - Sourcing erase job deletes by supplier id at run time. The gateway releases the id on finalize, so if the job is still retrying (backoff up to 1 h, max attempts)
   when an admin approves a *new* claim on the same id, the retry could delete the new owner's fresh listings. Carry a claim epoch/created-before timestamp in the job.
4. LOW - OPEN (trust reports have no account signal; needs gateway-supplied account age/verified-email header, see docs/requests/trust-media-ownership.md). Trust report store makes room at capacity by evicting the oldest rejected, then oldest pending, reports: many throwaway accounts (5 reports/h each) can push out
   pending reports from moderation. Same account-age / verified-email gate as feed/freight reports (see d, item 3).
5. LOW - `DELETE /v1/me` with a stolen access token allows password guessing at 3 attempts/min per user (events are audited). Acceptable; lock re-auth after N failures if desired.
6. LOW - PostgreSQL audit trigger covers UPDATE/DELETE only, not `TRUNCATE`; revoke TRUNCATE from the app role in the deploy docs.
7. LOW - Internal-token guard still fails open when `FF_INTERNAL_TOKEN` is unset and `FF_ENV` is not production (known, c item 1); in that mode `X-Client-Ip` and `/v1/internal/users/*` are spoofable by anyone who can reach the service port.
8. INFO - Signed media URLs are bearer links for 5 min (replayable by anyone holding the URL, by design); the response is `no-store`, `no-referrer`. A viewer carrying a *different* user's bearer gets 404 even with a valid link.
