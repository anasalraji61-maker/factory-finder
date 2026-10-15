# payments (port 8111)

Platform commission and deal payments (ROADMAP Phase 6 prep), crypto first: invoices, payment attempts, an
append-only double-entry ledger, provider webhooks. Internal only (reached through the gateway at
`/v1/invoices`, `/v1/ledger`, `/v1/payments`).

> **Compliance note.** This service is NOT a licensed payment institution, money transmitter or exchange.
> Crypto is only ever received into the platform owner's OWN wallets (a public receiving address from the
> environment; this service never reads, stores or logs a private key and never sends funds). Refunds are
> bookkeeping only; the transfer back is manual. Consult qualified counsel (licensing, AML/KYC, sanctions,
> tax, consumer protection) in the relevant jurisdictions BEFORE any live launch.

- Run: `uvicorn ff_payments.main:app --port 8111`; tests: `../../.venv/bin/python -m pytest -q`
- Contract: `contracts/openapi/payments.yaml`. `X-User-Id` required (401); `X-Internal-Token` checked only when `FF_INTERNAL_TOKEN` is set (not for `/health`, `/ready`, webhooks).
- Invoice status machine (`domain/state.py`): pending -> awaiting_payment -> confirming -> paid -> refunded; expired / failed / refunded are terminal. A confirming invoice never expires.
- Access: an invoice is visible to its payer, its payee and admins; anyone else gets 404 (no id probing). A deal owner (the rfq buyer, checked through `clients/deals.py` against rfq) can only create invoices whose amount comes from the deal; overrides are admin only.
- Admin = `X-Admin-Token` equal to `FF_PAYMENTS_ADMIN_TOKEN` (constant-time compare; disabled when unset; the gateway never forwards it).
- Commission (`domain/commission.py`, mirrors rfq): product 3%, raw material 2%, production line 4%, minimum 25 USD, half-up cents.
- Ledger (`ledger_entries`): one row per leg, `group_id` groups legs; debits == credits per group is enforced before insert; the ORM refuses UPDATE/DELETE. Payment: debit `clearing:<provider>`, credit `revenue:commission` or `payable:<payee>`; refund appends the reversed group.
- Money is a decimal string everywhere (fiat 2 decimals, USDT 6); JSON numbers are rejected.
- Expiry is lazy on every read and eager via `POST /v1/payments/sweep` (admin; call it from a scheduler), which also polls the provider.
- Webhook `POST /v1/payments/webhooks/{provider}`: header `X-FF-Signature: t=<unix>,v1=<hex>` = HMAC-SHA256(secret, `"<t>.<raw body>"`), 300 s tolerance, replay protection by `(provider, event_id)`, wrong amounts never settle. The gateway requires auth for this path, so a public ingress that bypasses the gateway is needed before real providers can call it.
- Late / wrong money is never dropped: a confirmed event for an expired or cancelled invoice (webhooks expire overdue invoices first), a `paid` event with the wrong amount, or a transfer the sweep finds for an invoice expired in the last 7 days sets `status_reason` to `late_payment_review` / `amount_mismatch_review` (status unchanged, nothing posted to the ledger) and is listed by admin `GET /v1/payments/review`; prune keeps their evidence. Admin `GET /v1/ledger/deals/{deal_id}/commission` = commission per deal net of refunds.
- Providers (`FF_PAYMENTS_PROVIDER`): `mock` (default, deterministic, test hook `MockProvider.confirm`), `usdt_tron` (UNVERIFIED against a live chain or explorer (see docs/fixes/payments-usdt-review-2026-10.md); address checked by base58check; a confirming tx that disappears reverts to awaiting; invoices get a unique sub-cent amount suffix as the match key, confirmed after N blocks), `off` (creation returns 503).

| Env | Default |
|---|---|
| `FF_PAYMENTS_DATABASE_URL` | `sqlite+aiosqlite:///./payments.db` |
| `FF_PAYMENTS_PROVIDER` | `mock` (`usdt_tron`, `off`) |
| `FF_PAYMENTS_ADMIN_TOKEN` | unset (admin disabled) |
| `FF_PAYMENTS_WEBHOOK_SECRET_MOCK` / `_USDT_TRON` | unset (webhooks answer 503) |
| `FF_PAYMENTS_WEBHOOK_TOLERANCE_SECONDS` | `300` |
| `FF_PAYMENTS_INVOICE_TTL_MINUTES` | `60` |
| `FF_PAYMENTS_RFQ_URL` / `_DEAL_CLIENT` | `http://localhost:8105` / `http` (or `mock`) |
| `FF_PAYMENTS_COMMISSION_PRODUCT` / `_RAW_MATERIAL` / `_PRODUCTION_LINE` | `0.03` / `0.02` / `0.04` |
| `FF_PAYMENTS_MIN_COMMISSION_USD` | `25` |
| `FF_PAYMENTS_USDT_RECEIVE_ADDRESS` / `_CONTRACT` / `_EXPLORER_URL` / `_EXPLORER_API_KEY` | unset (env only) |
| `FF_PAYMENTS_USDT_MIN_CONFIRMATIONS` | `20` |

## Ops (logging / readiness)
`GET /ready`: 503 when the database is unreachable. One JSON log line per request (route template, status, duration, user id); never query strings, bodies, tokens, signatures, memos or addresses. Code: `obs.py` (self-contained copy). Migrations: `alembic upgrade head` (see docs/DB.md).

## rfq callback outbox
Every `paid`/`refunded` transition queues an event for rfq in the same transaction; delivered inline (best effort) and by `POST /v1/payments/sweep`. Admin: `GET /v1/payments/outbox`, `POST /v1/payments/outbox/{id}/requeue`. Env: `FF_PAYMENTS_OUTBOX_MAX_ATTEMPTS`, `_OUTBOX_BACKOFF_SECONDS`, `_OUTBOX_LEASE_SECONDS`, `_OUTBOX_INLINE_TIMEOUT_SECONDS`. See `docs/decisions/deal-payment-hook.md`.

### Limits and retention (env)
`FF_PAYMENTS_MAX_OPEN_INVOICES_PER_USER` (20), `_MAX_INVOICES_PER_USER_PER_DAY` (50), `_WEBHOOK_EVENT_RETENTION_DAYS` (180), `_OUTBOX_DELIVERED_RETENTION_DAYS` (180), `_ATTEMPT_RETENTION_DAYS` (365); 0 disables a rule. Retention runs in `POST /v1/payments/sweep` and never touches invoices, ledger, paid/refunded history or undelivered outbox events.

## Environment reference (complete)
Every setting in `src/ff_payments/config.py` (`Settings`, case-insensitive env names; empty values count as unset). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_PAYMENTS_DATABASE_URL` | sqlite+aiosqlite:///./payments.db |
| `FF_PAYMENTS_DB_AUTO_CREATE` | unset |
| `FF_PAYMENTS_PROVIDER` | mock |
| `FF_PAYMENTS_INTERNAL_TOKEN` | unset |
| `FF_PAYMENTS_ADMIN_TOKEN` | unset |
| `FF_PAYMENTS_WEBHOOK_SECRET_MOCK` | unset |
| `FF_PAYMENTS_WEBHOOK_SECRET_USDT_TRON` | unset |
| `FF_PAYMENTS_WEBHOOK_TOLERANCE_SECONDS` | 300 |
| `FF_PAYMENTS_INVOICE_TTL_MINUTES` | 60 |
| `FF_PAYMENTS_RFQ_URL` | http://localhost:8105 |
| `FF_PAYMENTS_DEAL_CLIENT` | http |
| `FF_PAYMENTS_OUTBOX_MAX_ATTEMPTS` | 8 |
| `FF_PAYMENTS_OUTBOX_BACKOFF_SECONDS` | 30 |
| `FF_PAYMENTS_OUTBOX_LEASE_SECONDS` | 60 |
| `FF_PAYMENTS_OUTBOX_INLINE_TIMEOUT_SECONDS` | 3.0 |
| `FF_PAYMENTS_MAX_OPEN_INVOICES_PER_USER` | 20 |
| `FF_PAYMENTS_MAX_INVOICES_PER_USER_PER_DAY` | 50 |
| `FF_PAYMENTS_WEBHOOK_EVENT_RETENTION_DAYS` | 180 |
| `FF_PAYMENTS_OUTBOX_DELIVERED_RETENTION_DAYS` | 180 |
| `FF_PAYMENTS_ATTEMPT_RETENTION_DAYS` | 365 |
| `FF_PAYMENTS_COMMISSION_PRODUCT` | 0.03 |
| `FF_PAYMENTS_COMMISSION_RAW_MATERIAL` | 0.02 |
| `FF_PAYMENTS_COMMISSION_PRODUCTION_LINE` | 0.04 |
| `FF_PAYMENTS_MIN_COMMISSION_USD` | 25 |
| `FF_PAYMENTS_USDT_RECEIVE_ADDRESS` | unset |
| `FF_PAYMENTS_USDT_EXPLORER_URL` | unset |
| `FF_PAYMENTS_USDT_EXPLORER_API_KEY` | unset |
| `FF_PAYMENTS_USDT_CONTRACT` | unset |
| `FF_PAYMENTS_USDT_MIN_CONFIRMATIONS` | 20 |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default), `FF_ENV=production` refuses to start without `FF_INTERNAL_TOKEN` (see `docs/OPS.md`).
