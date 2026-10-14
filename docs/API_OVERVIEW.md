# API overview

Generated from `contracts/openapi/*.yaml` (the source of truth) and `services/gateway/src/ff_gateway/routing.py` (prefix table).
Regenerate by re-reading the contracts if they change; counts below are operations (method + path) per contract.

- Clients (mobile app, admin console) talk **only to the gateway** (`:8000`). It authenticates (JWT Bearer), rate-limits, and proxies by path prefix to the services below, adding `X-User-Id` and `X-Internal-Token`.
- In docker compose only the gateway publishes a port; the other ports are internal to the compose network. Ports shown are the compose ports (the sourcing contract lists `localhost:8002` as its dev server URL; compose uses 8101).
- Public (no login) at the gateway: `/health`, `/ready`, `/v1/auth/*`, `GET /v1/search`, `/v1/listings`, `/v1/suppliers`, `/v1/categories`, `/v1/countries`, `/v1/cities`, `/v1/hubs`, `/v1/fx/rates`, `/v1/hs`, `/v1/media/files`, and `POST /v1/quotes/landed-cost`. Everything else under `/v1` needs a Bearer token. `/v1/admin/*` needs `X-Admin-Token`.
- `POST /v1/alerts/evaluate` and `POST /v1/alerts/digest` are internal-only and never reachable through the gateway.
- `GET /v1/suppliers/{id}/reviews` and `/review-summary` are served by rfq even though `/v1/suppliers` otherwise belongs to sourcing.
- WebSocket chat: `GET /v1/ws/conversations/{conversation_id}` on the gateway.
- Payment-provider webhooks (`POST /v1/payments/webhooks/{provider}`) cannot carry a user token; see the ingress notes in `docs/DEPLOY.md`.

## Services

| Service | Port (compose) | Contract | Routes |
|---|---|---|---|
| gateway | 8000 | `contracts/openapi/gateway.yaml` | 35 |
| sourcing | 8101 | `contracts/openapi/sourcing.yaml` | 19 |
| logistics | 8102 | `contracts/openapi/logistics.yaml` | 8 |
| geo | 8103 | `contracts/openapi/geo.yaml` | 7 |
| trust | 8104 | `contracts/openapi/trust.yaml` | 7 |
| rfq | 8105 | `contracts/openapi/rfq.yaml` | 27 |
| messaging | 8106 | `contracts/openapi/messaging.yaml` | 8 |
| tracking | 8107 | `contracts/openapi/tracking.yaml` | 9 |
| notifications | 8108 | `contracts/openapi/notifications.yaml` | 18 |
| assistant | 8109 | `contracts/openapi/assistant.yaml` | 3 |
| demand | 8110 | `contracts/openapi/demand.yaml` | 13 |
| payments | 8111 | `contracts/openapi/payments.yaml` | 12 |
| media | 8112 | `contracts/openapi/media.yaml` | 5 |

### gateway (port 8000, the only published port)

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (dependencies reachable) |
| POST | `/v1/auth/register` | register |
| POST | `/v1/auth/login` | login |
| POST | `/v1/auth/refresh` | Rotating refresh - each refresh token is single-use; replaying a used one revokes the family (401) |
| POST | `/v1/auth/logout` | Revoke the refresh token's whole family (idempotent; always 204) |
| POST | `/v1/auth/verify-email` | Consume an email verification token (single use, hashed at rest, TTL 24 h) |
| POST | `/v1/auth/resend-verification` | Re-send the verification mail (always 202; no account enumeration; throttled per address) |
| GET | `/v1/me` | getMe |
| PATCH | `/v1/me` | patchMe |
| GET | `/v1/admin/supplier-claims` | listSupplierClaims |
| POST | `/v1/admin/supplier-claims/{user_id}/approve` | approveSupplierClaim |
| POST | `/v1/admin/supplier-claims/{user_id}/reject` | rejectSupplierClaim |
| GET | `/v1/admin/overview` | adminOverview |
| GET | `/v1/admin/demand/signals` | adminListSignals |
| POST | `/v1/admin/demand/signals` | adminImportSignal |
| POST | `/v1/admin/demand/signals/poll` | adminPollSignals |
| GET | `/v1/admin/demand/drafts` | adminListDrafts |
| GET | `/v1/admin/demand/quota` | adminDemandQuota |
| GET | `/v1/admin/demand/drafts/{id}` | adminGetDraft |
| POST | `/v1/admin/demand/drafts/{id}/approve` | adminApproveDraft |
| POST | `/v1/admin/demand/drafts/{id}/reject` | adminRejectDraft |
| POST | `/v1/admin/demand/drafts/{id}/mark-published` | adminMarkPublishedDraft |
| POST | `/v1/admin/demand/drafts/{id}/outcome` | adminOutcomeDraft |
| GET | `/v1/admin/demand/signals/{id}` | adminGetSignal |
| GET | `/v1/admin/payments/outbox` | adminPaymentsOutboxList |
| POST | `/v1/admin/payments/outbox/{id}/requeue` | adminPaymentsOutboxRequeue |
| GET | `/v1/admin/moderation/{path}` | adminModerationGet |
| POST | `/v1/admin/moderation/{path}` | adminModerationPost |
| PUT | `/v1/admin/moderation/{path}` | adminModerationPut |
| PATCH | `/v1/admin/moderation/{path}` | adminModerationPatch |
| DELETE | `/v1/admin/moderation/{path}` | adminModerationDelete |
| GET | `/v1/home` | getHome |
| GET | `/v1/{proxied_path}` | proxy |
| GET | `/v1/ws/conversations/{conversation_id}` | wsConversation |

### sourcing (internal port 8101)

**Gateway prefix `/v1/categories`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/categories` | Bilingual category tree (top level = listing kinds) |

**Gateway prefix `/v1/listings`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/listings/{id}` | Listing detail |
| POST | `/v1/listings/{id}/report` | Report a published listing (signed-in user) |

**Gateway prefix `/v1/my`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/my/listings` | Create a listing owned by the calling (verified) supplier; starts as draft |
| GET | `/v1/my/listings` | List the caller's own listings (all statuses), newest first |
| GET | `/v1/my/listings/{id}` | One of the caller's listings (404 for anyone else's) |
| PUT | `/v1/my/listings/{id}` | Replace the listing's content (status is unchanged) |
| DELETE | `/v1/my/listings/{id}` | Permanently delete the listing |
| POST | `/v1/my/listings/{id}/publish` | Make the listing searchable (draft or archived -> published) |
| POST | `/v1/my/listings/{id}/unpublish` | Remove the listing from search (published -> archived) |

**Gateway prefix `/v1/search`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/search` | Search listings across enabled sources (Arabic or English query) |

**Gateway prefix `/v1/sources`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/sources` | Registered sources, enabled flag, health and compliance note |

**Gateway prefix `/v1/suppliers`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/suppliers/{id}` | Supplier profile (with trust band) |

**/v1/admin (service admin API; gateway exposes it only through its token-guarded /v1/admin/moderation/* proxy)**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/admin/moderation/reports` | List user reports (admin) |
| GET | `/v1/admin/moderation/listings` | List listings that are pending_review or hidden (admin) |
| POST | `/v1/admin/moderation/listings/{id}/hide` | Hide a listing (admin); open reports become actioned |
| POST | `/v1/admin/moderation/listings/{id}/restore` | Restore a hidden/pending_review listing to its previous status (admin); open reports become dismissed |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (dependencies reachable) |

### logistics (internal port 8102)

**Gateway prefix `/v1/carriers`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/carriers` | Carrier / forwarder directory (mock) |

**Gateway prefix `/v1/fx`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/fx/rates` | Rates per 1 unit of base |
| POST | `/v1/fx/convert` | Convert an amount |

**Gateway prefix `/v1/hs`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/hs/search` | HS-code finder (curated, indicative dataset; confirm with a customs broker) |
| GET | `/v1/hs/{code}` | One HS subheading by 6-digit code (dots and 8/10-digit national codes are truncated to 6) |

**Gateway prefix `/v1/quotes`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/quotes/landed-cost` | Landed cost to the buyer's city, one option per feasible mode (sorted by total, one recommended) |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (dependencies reachable) |

### geo (internal port 8103)

**Gateway prefix `/v1/cities`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/cities` | Search cities (Arabic or English, diacritics/alef/ya/ta-marbuta insensitive) |

**Gateway prefix `/v1/countries`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/countries` | List supported countries |

**Gateway prefix `/v1/distance`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/distance` | Distance estimate between two points |

**Gateway prefix `/v1/hubs`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/hubs` | List hubs located in, or serving, a country |
| GET | `/v1/hubs/nearest` | Nearest hubs to a coordinate (straight-line), ascending distance |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (dependencies reachable) |

### trust (internal port 8104)

**Gateway prefix `/v1/trust`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/trust/suppliers/{supplier_id}` | getSupplierTrust |
| GET | `/v1/trust/suppliers:batch` | batchSupplierTrust |
| POST | `/v1/trust/evaluate` | evaluateTrust |
| GET | `/v1/trust/suppliers/{supplier_id}/history` | Score over time (oldest first), from stored snapshots plus deterministic mock history |
| POST | `/v1/trust/suppliers/{supplier_id}/report` | Buyer-submitted concern. Stored as pending_review; affects the score only after moderator acceptance. |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (dependencies reachable) |

### rfq (internal port 8105)

**Gateway prefix `/v1/deals`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/deals` | The caller's own deals, newest first (buyer = X-User-Id is buyer; supplier = X-User-Id is the offer owner). Never includes other parties' deals. |
| GET | `/v1/deals/{id}` | Deal (buyer or supplier only; others get 404) |
| POST | `/v1/deals/{id}/fulfilment/start` | Supplier starts fulfilment (paid -> in_fulfilment; idempotent) |
| POST | `/v1/deals/{id}/delivered` | Supplier marks the goods shipped / delivered (sets delivered_at; idempotent) |
| POST | `/v1/deals/{id}/confirm-receipt` | Buyer confirms receipt (in_fulfilment -> completed; idempotent) |
| GET | `/v1/deals/{id}/events` | Immutable event log of a deal (buyer or supplier; others 404), oldest first |
| POST | `/v1/deals/{id}/reviews` | Buyer reviews a deal (once per deal) |

**Gateway prefix `/v1/offers`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/offers/{id}/accept` | Buyer accepts an offer -> Deal with commission; other offers are rejected, request becomes awarded |
| POST | `/v1/offers/{id}/reject` | Buyer rejects an offer |
| POST | `/v1/offers/{id}/withdraw` | Supplier withdraws their offer |

**Gateway prefix `/v1/requests`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/requests` | Post a buyer request |
| GET | `/v1/requests` | My requests (scope=mine, default) or the public feed of others' live requests (scope=public) |
| GET | `/v1/requests/{id}` | Request detail (link-accessible, including private ones) |
| POST | `/v1/requests/{id}/close` | Buyer closes the request (active offers are rejected) |
| GET | `/v1/requests/{id}/suggestions` | Matching listings from sourcing (buyer only) |
| POST | `/v1/requests/{id}/offers` | Supplier submits an offer (not on own request; request must be open/negotiating) |
| GET | `/v1/requests/{id}/offers` | Offers on a request (buyer sees all, a supplier only their own) |
| GET | `/v1/requests/{id}/deal` | Accepted deal of a request (request owner/buyer only; 404 for anyone else or when not awarded yet) |

**Gateway prefix `/v1/reviews`**

| Method | Path | Summary |
|---|---|---|
| PUT | `/v1/reviews/{id}` | Buyer edits own review (within 24h of creation; prior values kept in the audit trail) |
| DELETE | `/v1/reviews/{id}` | Buyer deletes own review (within 24h; soft delete, stops counting, audit trail kept) |
| POST | `/v1/reviews/{id}/reply` | The verified supplier of the deal posts one public reply (<= 500 chars) |
| POST | `/v1/reviews/{id}/report` | Report abuse (marks flagged_for_review, never auto-hides; idempotent per user; 10 reports/hour/user -> 429) |

**Gateway prefix `/v1/suppliers`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/suppliers/{supplier_ref}/reviews` | Public reviews of a supplier (no auth; deleted reviews excluded) |
| GET | `/v1/suppliers/{supplier_ref}/review-summary` | Review aggregates of a supplier (public, no auth; input for the trust rating signal) |

**/v1/internal (NOT routed by the gateway)**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/internal/deals/{id}/payment-status` | INTERNAL (payments -> rfq). Never routed by the gateway (404 publicly). |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (dependencies reachable) |

### messaging (internal port 8106)

**Gateway prefix `/v1/conversations`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/conversations` | listConversations |
| POST | `/v1/conversations` | createConversation |
| GET | `/v1/conversations/{id}` | getConversation |
| GET | `/v1/conversations/{id}/messages` | listMessages |
| POST | `/v1/conversations/{id}/messages` | sendMessage |
| POST | `/v1/conversations/{id}/read` | markRead |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (dependencies reachable) |

### tracking (internal port 8107)

**Gateway prefix `/v1/shipments`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/shipments` | Track a container / bill of lading / air waybill / vessel IMO (idempotent per user+reference -> 409 duplicate_shipment) |
| GET | `/v1/shipments` | My shipments, newest first |
| GET | `/v1/shipments/{id}` | Shipment with its event timeline (404 if not owned by the caller) |
| DELETE | `/v1/shipments/{id}` | Stop tracking |
| POST | `/v1/shipments/{id}/refresh` | Pull the latest events from the provider |

**Gateway prefix `/v1/validate`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/validate/{reference_type}/{reference}` | Validate a reference (ISO 6346 / AWB mod-7 / IMO check digit / basic B/L) and detect the carrier |

**/v1/internal (NOT routed by the gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/internal/outbox-status` | Notification outbox / relay counters (internal; X-Internal-Token when FF_INTERNAL_TOKEN is set; no X-User-Id) |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (dependencies reachable) |

### notifications (internal port 8108)

**Gateway prefix `/v1/alerts`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/alerts` | listAlerts |
| POST | `/v1/alerts/evaluate` | evaluateAlerts |
| POST | `/v1/alerts/read-all` | markAllAlertsRead |
| POST | `/v1/alerts/{id}/read` | markAlertRead |
| POST | `/v1/alerts/digest` | sendDigests |

**Gateway prefix `/v1/devices`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/devices` | listDevices |
| POST | `/v1/devices` | registerDevice |
| DELETE | `/v1/devices/{id}` | deleteDevice |

**Gateway prefix `/v1/notification-prefs`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/notification-prefs` | getNotificationPrefs |
| PUT | `/v1/notification-prefs` | putNotificationPrefs |
| POST | `/v1/notification-prefs/verify-email` | verifyDigestEmail |
| POST | `/v1/notification-prefs/resend-code` | resendDigestEmailCode |

**Gateway prefix `/v1/watchlist`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/watchlist` | listWatchlist |
| POST | `/v1/watchlist` | addWatch |
| DELETE | `/v1/watchlist/{id}` | deleteWatch |

**/v1/internal (NOT routed by the gateway)**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/internal/tracking-events` | ingestTrackingEvents |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (dependencies reachable) |

### assistant (internal port 8109)

**Gateway prefix `/v1/assistant`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/assistant/query` | Arabic/English natural-language query -> intent, structured query and one combined answer (answer_text is in the language detected from the query, Arabic by default) |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (dependencies reachable) |

### demand (internal port 8110)

**/v1/drafts (admin-only: gateway exposes it as /v1/admin/demand/drafts*)**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/drafts` | listDrafts |
| GET | `/v1/drafts/{id}` | getDraft |
| POST | `/v1/drafts/{id}/approve` | approveDraft |
| POST | `/v1/drafts/{id}/reject` | rejectDraft |
| POST | `/v1/drafts/{id}/mark-published` | markPublished |
| POST | `/v1/drafts/{id}/outcome` | recordOutcome |

**/v1/quota (admin-only: gateway exposes it as /v1/admin/demand/quota*)**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/quota` | getQuota |

**/v1/signals (admin-only: gateway exposes it as /v1/admin/demand/signals*)**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/signals` | importSignal |
| GET | `/v1/signals` | listSignals |
| POST | `/v1/signals/poll` | pollSignals |
| GET | `/v1/signals/{id}` | getSignal |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (dependencies reachable) |

### payments (internal port 8111)

**Gateway prefix `/v1/invoices`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/invoices` | createInvoice |
| GET | `/v1/invoices` | listInvoices |
| GET | `/v1/invoices/{id}` | getInvoice |
| POST | `/v1/invoices/{id}/cancel` | cancelInvoice |
| POST | `/v1/invoices/{id}/refund` | refundInvoice |

**Gateway prefix `/v1/ledger`**

| Method | Path | Summary |
|---|---|---|
| GET | `/v1/ledger` | listLedger |

**Gateway prefix `/v1/payments`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/payments/sweep` | sweepPayments |
| GET | `/v1/payments/outbox` | listOutbox |
| POST | `/v1/payments/outbox/{id}/requeue` | requeueOutbox |
| POST | `/v1/payments/webhooks/{provider}` | receiveWebhook |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (database reachable) |

### media (internal port 8112)

**Gateway prefix `/v1/media`**

| Method | Path | Summary |
|---|---|---|
| POST | `/v1/media/images` | Upload an image (multipart/form-data) |
| DELETE | `/v1/media/images/{id}` | Delete an image (owner only; 404 for anyone else, never 403) |
| GET | `/v1/media/files/{filename}` | Image bytes (PUBLIC, no auth) |

**probes (direct to service port, not via gateway)**

| Method | Path | Summary |
|---|---|---|
| GET | `/health` | health |
| GET | `/ready` | Readiness (database reachable and storage writable) |