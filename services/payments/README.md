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
- Providers (`FF_PAYMENTS_PROVIDER`): `mock` (default, deterministic, test hook `MockProvider.confirm`), `usdt_tron` (UNVERIFIED against a live chain or explorer; invoices get a unique sub-cent amount suffix as the match key, confirmed after N blocks), `off` (creation returns 503).

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
