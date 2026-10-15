# Account deletion and data export

Decision log for the in-app account deletion and privacy export required by Google Play and the App Store.
Owner: gateway, with additive internal endpoints in every service that holds user data.

## Decisions

- 2026-10-15 `DELETE /v1/me` re-authenticates with the current password or a current, unused refresh token (no OTP, because mail/SMS are optional in this stack). Wrong proofs are audited and rate limited.
- 2026-10-15 Soft-delete, then anonymize. The gateway row keeps its `id` (referential integrity for services that keep pseudonymous ids), but email, phone, name, company, destination, supplier claim and password hash are scrubbed, all refresh and verification tokens are removed, and the account is inactive. `FF_GATEWAY_DELETION_GRACE_DAYS` (default 0) delays the anonymization; a login with the correct password inside the grace period cancels it.
- 2026-10-15 Erasure in the services is a fan-out of `DELETE /v1/internal/users/{id}/data`, stored as one durable `deletion_jobs` row per service (gateway DB). Jobs run immediately, then retry with exponential backoff (60 s doubling, max 1 h) up to `FF_GATEWAY_DELETION_MAX_ATTEMPTS` (12); then they are `dead` and show in `GET /v1/admin/account-deletions?status=dead`. A repeated `DELETE /v1/me` reports the status and retries pending services at once (idempotent).
- 2026-10-15 Export is `GET /v1/me/export`: a streamed JSON bundle (profile + `POST /v1/internal/users/{id}/export` of each service). Each call has a timeout (`FF_GATEWAY_PRIVACY_TIMEOUT_SECONDS`, 10 s); a failing service is reported per service and sets `partial: true`; the bundle is capped (`FF_GATEWAY_EXPORT_MAX_BYTES`, 5 MiB; also per service). Each service also caps its own rows (about 500 to 5000) and flags `truncated`.
- 2026-10-15 Internal routes are guarded by `FF_INTERNAL_TOKEN` and answer **404** to anything else. The gateway never routes `/v1/internal/*` publicly (no route prefix), so a client cannot reach them. The gateway only ever sends the authenticated caller's id. Without a configured token (dev only) the routes are open like every other service route; `FF_ENV=production` already refuses to start without the token.
- 2026-10-15 Audit: durable `account_events` table (opaque user id, event name, counters, request id) plus one JSON log line per event. Never an email, phone, name or token.

## What each service does on erasure

| Service | Export | Erasure | Kept |
|---|---|---|---|
| gateway | profile | row anonymized, tokens removed | user id, `account_events`, `deletion_jobs` |
| notifications | watches, alerts, devices (token masked), prefs | all rows of the owner deleted | nothing |
| messaging | conversations, sent messages | participant, sender, `created_by` replaced by a tombstone; attachment references on the user's messages removed | the thread and message text, for the counterparty |
| feed | posts, comments, follows, likes, reports | follows, likes, rate counters deleted; comments become a deleted marker (`[deleted]`); posts authored by the user deleted with their likes, comments and reports; reports kept with a tombstoned reporter | moderation reports (tombstoned) |
| freight | applications, forwarder profile, requests, quotes, ratings, reports | ids tombstoned, free text scrubbed; open requests closed; open quotes withdrawn; forwarder suspended; rating comment removed | awarded requests (cargo text kept for the awarded forwarder), accepted quotes, rating stars |
| rfq | requests, offers, deals, reviews | request text, offer notes, review text and replies scrubbed; open requests cancelled; active offers withdrawn; reviews marked deleted | **deals, deal events, accepted offers** (financial/audit), user ids |
| media | file metadata | files, variants and quota rows deleted | nothing |
| trust | buyer reports | reporter id tombstoned | report text (abuse evidence), **verification documents and the append-only audit** (supplier business records) |
| payments | invoices | only the free-text memo is blanked | **invoices, ledger, attempts, webhook events, outbox** (immutable financial records) |
| sourcing | listings of the verified supplier, listing reports | the verified supplier's native listings deleted; report details blanked | other users' reports |
| tracking | shipments | shipments and outbox rows deleted | nothing |
| assistant | quota counter | counter dropped | nothing (no conversation storage) |
| demand | nothing | nothing | signals come from public posts, not from users |
| logistics, geo | nothing | n/a | n/a |

## Retention exceptions (to state in the privacy policy)

1. **Payments ledger, invoices, webhook events and outbox, rfq deals and deal events**: kept for financial audit, tax and dispute handling. They hold pseudonymous user ids only, and the gateway row no longer links to a person.
2. **Trust verification documents and `verification_audit`**: business verification records of a supplier; the audit table is append-only by trigger.
3. **Counterparty records**: message text in shared threads, awarded freight requests and accepted offers stay so the other party keeps their history.
4. **Moderation and abuse evidence** (reports): kept with the reporter anonymized.
5. **Gateway audit** (`account_events`, `deletion_jobs`): opaque ids and counters only; kept to prove deletion happened.
6. **Backups**: erased data disappears from backups on their normal rotation (state the period in the policy).

## Known gaps

- Verification document files in media are deleted with the user's media while trust keeps the document row (a dangling file reference). Review with the owner whether verification files must be kept for the audit period.
- Open WebSocket connections are not closed at deletion; they end at token expiry (15 min) and cannot reconnect.
- The mobile app has no deletion screen yet (the API is ready).
- `sourcing` deletes listings of a verified supplier; whether a company should keep them after its representative leaves is a policy choice.
