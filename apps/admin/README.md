# apps/admin

Small admin console (plain HTML + vanilla JS, no build step, no CDN). Arabic-first RTL with an English toggle. Tabs: **Supplier claims** (pending/verified filter, paging, approve/reject with confirm), **Account deletions** (incomplete erasure jobs, pending/dead, no PII), **Demand drafts** (filter by status, see the source post, edit text then approve, reject, mark published, record outcome, daily quota, poll-signals button), **Overview** (counts), **Moderation** (pending_review/hidden listings with hide + reason / restore, user reports with status filter), **Payments outbox** (status filter, requeue dead events), **Verification** (supplier verification documents: pending queue with approve [optional expiry] / reject [reason required] / set or clear expiry, per-document and global audit log; document numbers, masked numbers and file paths are never rendered), **Freight** (forwarder applications approve/reject, forwarders suspend/reinstate, reports, expire-overdue sweep), **Payments review** (read-only queue of invoices needing a human: late payment / amount mismatch; invoice and paid amounts shown as Decimal strings + currency, never converted to numbers; payer memo, pay address and pay URL never rendered; paging), **Feed** (reports, posts and comments hide with reason / restore).

It talks only to the gateway: `/v1/admin/supplier-claims*`, `/v1/admin/demand/*`, `/v1/admin/overview`, `/v1/admin/account-deletions`, `/v1/admin/media/files/{id}` (view only; the contract has no media delete/list route), `/v1/admin/moderation/*`, `/v1/admin/payments/outbox*`, `/v1/admin/payments/review` (GET, page/page_size; mirrors payments `GET /v1/payments/review`; 404 shows an "unavailable" notice), `/v1/admin/trust/verification/*`, `/v1/admin/freight/*`, `/v1/admin/feed/*` (the last three need FF_TRUST_ADMIN_TOKEN / FF_FREIGHT_ADMIN_TOKEN / FF_FEED_ADMIN_TOKEN on the gateway; 404 otherwise, see docs/decisions/gateway-trust-admin.md) with header `X-Admin-Token`.

## Run
- Same origin (recommended): start the gateway with `FF_GATEWAY_ADMIN_TOKEN=<secret> FF_GATEWAY_SERVE_ADMIN=true` and open `http://localhost:8000/admin/`. Leave the gateway URL empty at login.
- Separate static host (`python -m http.server -d apps/admin 8200`): list that origin in `FF_GATEWAY_CORS_ORIGINS='["http://localhost:8200"]'` and enter the gateway URL at login (or edit `config.js`). CORS stays closed by default.

## Security
- Token is kept in `sessionStorage` only (cleared on sign-out / tab close), never in localStorage, never logged, sent only in `X-Admin-Token`.
- All rendered text uses `textContent`; no `innerHTML`. CSP meta tag: scripts/styles from self only. Post URLs are shown as text, never as links.
- Serve over HTTPS outside localhost; the admin token is a shared secret.

## Tests
`node --test apps/admin/tests/lib.test.js` (path builders, body validation, `safeDoc` number redaction) (Node 18+, no dependencies, no network): path builders, reason validation, action gating, and static checks (no innerHTML/localStorage/console, CSP intact).
