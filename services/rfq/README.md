# rfq (port 8105)

Reverse marketplace: buyers post requests (product / raw material / production line), suppliers send offers,
the buyer accepts one and a Deal with platform commission is created.

- Run: `uvicorn ff_rfq.main:app --port 8105`; tests: `../../.venv/bin/python -m pytest -q`
- Contract: `contracts/openapi/rfq.yaml`. `X-User-Id` required on `/v1` (missing -> 401); `X-Internal-Token` checked only when `FF_INTERNAL_TOKEN` is set.
- Status machines in `domain/state.py`; commission in `domain/commission.py` (Decimal, half-up cents; min fee in USD converted with static reference rates).
- Expiry is lazy: deadlines / offer validity are evaluated on each call.
- Suggestions come from sourcing through `clients/sourcing.py` (httpx + deterministic mock; tests use the mock).

| Env | Default |
|---|---|
| `FF_RFQ_DATABASE_URL` | `sqlite+aiosqlite:///./rfq.db` |
| `FF_RFQ_SOURCING_URL` | `http://localhost:8101` |
| `FF_RFQ_SOURCING_CLIENT` | `http` (or `mock`) |
| `FF_RFQ_COMMISSION_PRODUCT` / `_RAW_MATERIAL` / `_PRODUCTION_LINE` | `0.03` / `0.02` / `0.04` |
| `FF_RFQ_MIN_COMMISSION_USD` | `25` |

Offer identity: owner = `X-User-Id`; `supplier_ref` = gateway-verified `X-Supplier-Id` (else null, `supplier_verified=false`). A `supplier_ref` in the request body is ignored; `supplier_name` is a display label only.


## Verified-deal reviews
Only the buyer of a deal in `paid | in_fulfilment | completed` may review it, once per deal (409 `review_already_exists`; deleting does not free the slot).
The deal's offer must carry a gateway-verified `supplier_ref` (else 409 `supplier_unverified`).
`POST /v1/deals/{id}/reviews`, `PUT|DELETE /v1/reviews/{id}` (author, within 24h of creation, else 409 `review_window_closed`),
`POST /v1/reviews/{id}/reply` (only `X-Supplier-Id` == review supplier, once, <=500), `POST /v1/reviews/{id}/report` (flag only, 10/hour/user -> 429),
public `GET /v1/suppliers/{ref}/reviews?page&page_size&sort=recent|rating` and `GET /v1/suppliers/{ref}/review-summary` (no auth; the gateway routes these two paths here).
Rating and sub-ratings are strict integers 1-5; title <=80, text <=1000; control/bidi chars stripped; links, emails and phone numbers -> 422 `prohibited_content`.
Reviewer is shown as "First L." from the gateway-set `X-User-Name` (never an email). Deleted reviews stop counting; every change is kept in `review_events`.
Code: `reviews.py`, `domain/review_text.py`; tables `reviews`, `review_events`, `review_reports` (migration `0002`). Decisions: `docs/decisions/deal-reviews.md`; trust wiring request: `docs/requests/trust-reviews.md`.

## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): 503 when the database is unreachable. Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

## Deal lifecycle
`POST /v1/deals/{id}/fulfilment/start|delivered|confirm-receipt`, `GET /v1/deals/{id}/events`, internal `POST /v1/internal/deals/{id}/payment-status` (payments callback, token-guarded, not routed by the gateway). Env: `FF_RFQ_REQUIRE_BOTH_INVOICES`. See `docs/decisions/deal-payment-hook.md`.

## Deal lookup
`GET /v1/deals?role=buyer|supplier|any&status=&page=&page_size=` lists only the caller's deals (buyer = `X-User-Id` is the buyer, supplier = `X-User-Id` is the offer owner, i.e. the same rule as `GET /v1/deals/{id}`), newest first (`created_at desc, id desc`, stable pages), same Deal JSON. `GET /v1/requests/{id}/deal` returns the accepted deal to the request owner only (404 otherwise / not awarded). Indexes: migration `0004`. Decision: `docs/decisions/rfq-deals-list.md`.
