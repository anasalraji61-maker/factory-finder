# API examples (curl through the gateway)

All calls go to the gateway (`http://localhost:8000`); never to a service port. Field names are taken from `contracts/openapi/*.yaml` and
`scripts/e2e*.py`. Start a stack with `python scripts/serve_stack.py` or `make dev`. Examples use `jq`.

```
GW=http://localhost:8000
```

## 1. Register, login, refresh (`gateway.yaml`)
Register needs `password` and `name` plus `email` or `phone`; the response (201) has `access_token`, `refresh_token` and `user`.
```
curl -s $GW/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"buyer@example.com","password":"Passw0rd!x","name":"Buyer One"}'
curl -s $GW/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"buyer@example.com","password":"Passw0rd!x"}' | tee /tmp/login.json
TOKEN=$(jq -r .access_token /tmp/login.json); REFRESH=$(jq -r .refresh_token /tmp/login.json)
curl -s $GW/v1/auth/refresh -H 'Content-Type: application/json' -d "{\"refresh_token\":\"$REFRESH\"}"   # new tokens, no user
curl -s -X PATCH $GW/v1/me -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"role":"buyer","default_destination":{"country_code":"IQ","city":"Baghdad"}}'
```
Access tokens last 15 minutes; refresh tokens 30 days. Use `-H "Authorization: Bearer $TOKEN"` on every non-public call below.

## 2. Search (`sourcing.yaml`, public)
Query params: `q, kind, condition, origin_country, category, min_price, max_price, moq_max, verified_only, sort, page, page_size`.
The response has `items` (each with `id`, `unit_price`, `supplier.trust_band`) and `facets`.
```
curl -s -G $GW/v1/search --data-urlencode 'q=injection molding machine' -d sort=price_asc -d page_size=20
curl -s $GW/v1/listings/LISTING_ID          # LISTING_ID from items[].id
```

## 3. Landed cost (`logistics.yaml`, public)
Required: `goods`, `origin`, `destination`. Optional: `supplier_incoterm`, `modes`, `display_currency`, `insurance`, `freight_override`.
The response has `options[]` (each with `mode`, `lines[]`, `total` as a `{min,max}` range) and `assumptions[]`; every non-goods line is an estimate with `as_of` and `source`.
```
curl -s $GW/v1/quotes/landed-cost -H 'Content-Type: application/json' -d '{
  "goods":{"description":"chairs","quantity":500,"total_value":{"amount":"5000","currency":"USD"},
           "total_weight_kg":3000,"total_volume_m3":30},
  "origin":{"country_code":"CN","city":"Shanghai"},
  "destination":{"country_code":"IQ","city":"Baghdad"},
  "display_currency":"USD"}'
```

## 4. Track a shipment: validate, then add (`tracking.yaml`)
`reference_type` is one of `container | bl | awb | vessel_imo`. Validation returns `valid`, `reason` (e.g. `check_digit`) and `suggestions` for typos.
```
curl -s $GW/v1/validate/container/CSQU3054383 -H "Authorization: Bearer $TOKEN"        # {"valid":true,...}
curl -s $GW/v1/validate/container/CSQU3O54383 -H "Authorization: Bearer $TOKEN"        # valid:false + suggestions
curl -s $GW/v1/shipments -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reference":"CSQU3054383","reference_type":"container","label":"chairs"}'      # 201, has id; 409 if already tracked
curl -s $GW/v1/shipments/SHIPMENT_ID -H "Authorization: Bearer $TOKEN"                   # timeline in events[]
curl -s -X POST $GW/v1/shipments/SHIPMENT_ID/refresh -H "Authorization: Bearer $TOKEN"  # throttled: may answer 429
```

## 5. Create an RFQ, offer, accept (`rfq.yaml`)
Request requires `kind`, `title`, `quantity`; offer requires `price` and `supplier_name` and is sent by a second user (role `supplier`).
Accepting creates a deal with `commission`. Only the request owner can accept or read the offers.
```
curl -s $GW/v1/requests -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "kind":"product","title":"Plastic chairs 500","quantity":500,"unit":"piece",
  "target_price":{"amount":"8","currency":"USD"},"destination":{"country_code":"IQ","city":"Erbil"}}'   # 201 -> id
curl -s $GW/v1/requests/REQUEST_ID/offers -H "Authorization: Bearer $SUPPLIER_TOKEN" -H 'Content-Type: application/json' -d '{
  "price":{"amount":"7.5","currency":"USD"},"supplier_name":"Supplier One","moq":100,"lead_time_days":20,"incoterm":"FOB"}'   # 201 -> id
curl -s $GW/v1/requests/REQUEST_ID/offers -H "Authorization: Bearer $TOKEN"
curl -s -X POST $GW/v1/offers/OFFER_ID/accept -H "Authorization: Bearer $TOKEN"   # deal (with commission), id is the deal id
curl -s $GW/v1/deals/DEAL_ID -H "Authorization: Bearer $TOKEN"
```

## 6. Freight request and quote (`freight.yaml`)
A forwarder first applies (`POST /v1/freight/applications`: `company_name, country_code, lanes[], modes[], incoterms[]`, optional
`description, certifications`; 409 on a duplicate) and an admin approves it with `X-Admin-Token` (admin approval is not available to users).
```
curl -s $GW/v1/freight/applications -H "Authorization: Bearer $FWD_TOKEN" -H 'Content-Type: application/json' -d '{
  "company_name":"Fast Cargo","country_code":"CN","description":"Sea freight",
  "lanes":[{"origin_country":"CN","destination_country":"IQ"}],"modes":["sea"],"incoterms":["FOB","CIF"]}'
curl -s -X POST $GW/v1/admin/freight/applications/APPLICATION_ID/approve -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"note":"ok"}'
# buyer: required origin_country, origin_place, destination_country, destination_place, cargo_description, mode, incoterm, ready_date
curl -s $GW/v1/freight/requests -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "origin_country":"CN","origin_place":"Shenzhen","destination_country":"IQ","destination_place":"Umm Qasr",
  "cargo_description":"Ceramic planters","weight_kg":"4200","volume_cbm":"18","mode":"sea","container_type":"40HC",
  "container_count":1,"incoterm":"FOB","ready_date":"2026-11-01","currency":"USD","quote_deadline_days":7}'
# approved forwarder: required amount, currency, transit_days
curl -s $GW/v1/freight/requests/REQUEST_ID/quotes -H "Authorization: Bearer $FWD_TOKEN" -H 'Content-Type: application/json' -d '{
  "amount":"3100","currency":"USD","transit_days":24,"valid_days":10,"inclusions":["THC"],
  "breakdown":[{"label":"Ocean freight","amount":"2800"},{"label":"THC","amount":"300"}]}'
curl -s $GW/v1/freight/requests/REQUEST_ID/comparison -H "Authorization: Bearer $TOKEN"
curl -s -X POST $GW/v1/freight/quotes/QUOTE_ID/accept -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"revision":1}'
```
`revision` must match the quote's current revision (a stale one is refused); revising a quote with `PUT /v1/freight/quotes/{id}` bumps it.

## 7. Invoice (mock provider) (`payments.yaml`)
The deal owner sends only `deal_id` and `kind` (`commission | deal_payment`); payer, payee and amount derive from the deal.
Repeating the call returns the same invoice (200 instead of 201). Status is one of `pending, awaiting_payment, confirming, paid, expired, failed, refunded`.
With `FF_PAYMENTS_PROVIDER=mock`, payment is confirmed by a signed webhook on the payments port (see `scripts/e2e.py`, `deal_lifecycle`), not through the gateway.
```
curl -s $GW/v1/invoices -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"deal_id":"DEAL_ID","kind":"commission"}'
curl -s $GW/v1/invoices/INVOICE_ID -H "Authorization: Bearer $TOKEN"
curl -s $GW/v1/invoices -H "Authorization: Bearer $TOKEN"
```

## 8. Assistant (`assistant.yaml`)
Body: `text` (required), `locale` (`ar` | `en`), optional `destination`. The response has `answer_text`, and depending on the question `listings`, `quote`/`quotes`
or `cards[]` (types such as `shipment_status`, `deal_status`, `listing_comparison`, `hs_code`, `rfq_draft`, `notice`; each card has `title` and `title_ar`).
A per-user daily quota answers 429 with `Retry-After`.
```
curl -s $GW/v1/assistant/query -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل","locale":"ar"}'
curl -s $GW/v1/assistant/query -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"where is my container CSQU3054383","locale":"en"}'
```

## 9. Recent additions
Each response body below is a validated file in `contracts/examples/` (checked by `make contract-examples`). Admin calls need `X-Admin-Token`
(`$ADMIN_TOKEN`); an optional `X-Reviewer` (charset `[A-Za-z0-9_.:-]`, max 64, default `admin`) is recorded in the audit logs.

**Payments needing review (admin, `gateway.yaml`).** Invoices flagged `late_payment_review` or `amount_mismatch_review`, oldest first.
Only `limit` (maps to `page_size`, max 100), `cursor`, `page`, `page_size` are accepted (others 422); 404 when the admin tokens are unset,
502/504 when payments is down/slow. Response: `payments.review_page.response.json` (`items, total, page, page_size`).
```
curl -s "$GW/v1/admin/payments/review?limit=20" -H "X-Admin-Token: $ADMIN_TOKEN" -H 'X-Reviewer: ops.anas'
```

**Supplier claim revoke and audit (admin, `gateway.yaml`).** Revoking a verified claim needs a `reason` (422 without; 409 `claim_not_verified`
otherwise); the response is the `SupplierClaim` (`supplier_id: null`, `supplier_claim_status: none`) and the old supplier id is released in trust.
The audit log lists `approve|reject|revoke|self_release` decisions, newest first (`user_id`, `limit` 1..500 filters).
Examples: `gateway.supplier_claim_revoke.response.json`, `gateway.supplier_claim_audit.response.json`.
```
curl -s -X POST $GW/v1/admin/supplier-claims/USER_ID/revoke -H "X-Admin-Token: $ADMIN_TOKEN" -H 'X-Reviewer: ops.anas' \
  -H 'Content-Type: application/json' -d '{"reason":"Documents found to be forged"}'
curl -s "$GW/v1/admin/supplier-claims/audit?user_id=USER_ID&limit=50" -H "X-Admin-Token: $ADMIN_TOKEN"
```

**Trust release (service-to-service, `trust.yaml`).** The gateway calls this on reject/revoke/`PATCH /v1/me` supplier change (best effort, only when
`FF_TRUST_ADMIN_TOKEN` is set), on the trust port, not through a public route. Live documents become withdrawn, all rows are hidden from the next
claimant; a repeat call returns zero counts. Example: `trust.supplier_release.response.json`.
```
curl -s -X POST $TRUST/v1/admin/trust/verification/suppliers/sup_demo_1/release -H "X-Admin-Token: $TRUST_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"reason":"claim revoked"}'
```

**Assistant RFQ draft (`assistant.yaml`).** A text such as "post a purchase request for 2000 kg of cotton delivered to Basra, target price 4 USD" gives
`intent: create_rfq_draft` and a card of `type: rfq_draft`. Nothing is created: `refs.deep_link` is `/requests/new`, `refs.draft` is `"true"`,
`refs.missing` lists the required keys still absent (`product, quantity, destination`, plus `unit`), and `refs.prefill_*` carry only values from the user's
text. Example: `assistant.create_rfq_draft.response.json`.
```
curl -s $GW/v1/assistant/query -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"post a purchase request for 2000 kg of cotton delivered to Basra, target price 4 USD","locale":"en"}' | jq '.cards[0].refs'
```

**Message idempotency (`messaging.yaml`).** `client_id` (alias of `client_message_id`, `[A-Za-z0-9_.:-]`, max 64) makes a send idempotent per sender and
conversation: first send 201, a retry returns the original message with 200, and the message echoes `client_id`. Examples:
`messaging.send_client_id.request.json`, `messaging.send_client_id.response.json`.
```
curl -s -X POST $GW/v1/conversations/CONV_ID/messages -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"text","text":"Is 500 units possible by December?","client_id":"app-7f3a9c1e-0001"}'
```

**Offer `comparable` (`rfq.yaml`).** On offers: `true` when the offer currency equals the request target currency, `false` when it differs (prices are
never converted implicitly), `null` when the request has no target price. Example: `rfq.offer_comparable.response.json` (CNY offer vs a USD target).
```
curl -s $GW/v1/requests/REQUEST_ID/offers -H "Authorization: Bearer $TOKEN"   # each offer has price and comparable
```

**More validated examples (`contracts/examples/`).** Real mock-service responses, checked by `make contract-examples`:
- `tracking.shipment_create.request.json` / `.response.json`: `POST /v1/shipments` and the 201 `Shipment` with its timeline.
- `logistics.landed_cost_forwarder_quote.response.json`: `freight_override` with `source: forwarder_quote`; the `main_leg` line is exact (`quoted: true`, `estimate: false`).
- `freight.comparison.response.json`: comparison rows with `rating_confidence`, `price_delta`, `cheaper_quote_ids`.
- `payments.invoice_amount_mismatch_review.response.json`: invoice kept `awaiting_payment` with `status_reason: amount_mismatch_review` after a wrong-amount webhook.
- `notifications.alerts_price_drop.response.json`: `GET /v1/alerts` after a 10% price drop (rule `price_drop`).
- `feed.post_create.response.json`: a supplier post (201).
- `media.upload_image.response.json`: multipart image upload (201).
- `geo.distance_sea_avoid.response.json`: `GET /v1/distance?mode=sea&avoid=suez,bab_el_mandeb`.
- `rfq.market_page.response.json`: `GET /v1/requests?scope=public&page_size=2` with `next_cursor` for `?cursor=`.

## Errors
Failures use the shared error shape (`error.code`, e.g. `not_found`, `deal_not_reviewable`); 401 without a token, 422 for invalid bodies, 429 with `Retry-After`.
