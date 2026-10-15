# Decision index

One decision file per agent or topic (`docs/decisions/<id>.md`, newest entries are appended). Cross-cutting decisions live in `docs/DECISIONS.md`. Last updated 2026-10-15; 101 files.

## Platform, gateway and ops

| File | Summary |
|---|---|
| [gateway.md](gateway.md) | Gateway MVP decisions (auth, routing, aggregation); refresh-token handling superseded by hardening. |
| [gateway-verify.md](gateway-verify.md) | Email verification: hashed single-use tokens via mail adapter (off/mock/smtp); optional enforcement flag. |
| [gateway-ws.md](gateway-ws.md) | Gateway proxies only the conversations WebSocket to messaging; auth via ticket or token. |
| [gateway-admin-payments.md](gateway-admin-payments.md) | Gateway allow-listed admin passthrough for payments outbox list and requeue. |
| [gateway-trust-admin.md](gateway-trust-admin.md) | Verification routes share the verified-supplier forwarding; trust/freight/feed admin passthroughs. |
| [supplier-chat.md](supplier-chat.md) | Suppliers are claimed by gateway users (first claimer wins); supplier id forwarded to messaging. |
| [supplier-claim-verify.md](supplier-claim-verify.md) | Claims start pending; X-Supplier-Id forwarded only when the claim is verified. |
| [account-deletion.md](account-deletion.md) | Account deletion and export: re-auth with password or refresh token, grace period, per-service erase fan-out with durable jobs. |
| [hardening.md](hardening.md) | Server-tracked single-use refresh tokens with reuse detection; other hardening fixes. |
| [ops-hardening.md](ops-hardening.md) | Per-service self-contained `obs.py` pure ASGI middleware (no shared package). |
| [db-migrations.md](db-migrations.md) | Alembic per stateful service, asyncpg for PostgreSQL, `FF_<SVC>_DB_AUTO_CREATE` switch. |
| [infra.md](infra.md) | Compose hardening: internal + egress networks, uvicorn flags, exec CMD. |
| [compose-run.md](compose-run.md) | Compose validated statically (no Docker pull in sandbox); documented in DEPLOY.md. |
| [admin-console.md](admin-console.md) | Admin console forwards a fixed `admin` actor to demand; shared admin token means no per-person identity. |
| [admin-media.md](admin-media.md) | Admin console views verification evidence via the gateway media admin read, rendered as blob URLs. |
| [admin-moderation.md](admin-moderation.md) | Moderation tab uses the existing `/v1/admin/moderation/*` passthrough (hide/restore with reason). |
| [security-review-2026-10-f.md](security-review-2026-10-f.md) | Retention inside existing sweeps; defaults 90-365 days; money records kept. |
| [security-review-g.md](security-review-g.md) | rfq row locking, offer caps, wide Decimal context; tracking caps; geo query length caps. |

## Sourcing and data

| File | Summary |
|---|---|
| [data.md](data.md) | Mock catalog grown to 165 listings / 83 suppliers across 11 origin countries. |
| [data-round-3.md](data-round-3.md) | Duty/VAT table extended by 29 destinations (70 total). |
| [real-adapters.md](real-adapters.md) | `HttpProviderAdapter` pattern for licensed sourcing APIs; Alibaba OpenAPI skeleton, off by default. |
| [search-quality.md](search-quality.md) | Rule-guarded typo tolerance and other search ranking rules. |
| [sourcing.md](sourcing.md) | Sourcing basics: mock catalog size and adapter registry decisions. |
| [sourcing-licensed-provider.md](sourcing-licensed-provider.md) | Generic licensed REST provider adapter driven by a declarative JSON mapping and validator CLI. |
| [sourcing-moderation.md](sourcing-moderation.md) | Listing statuses pending_review and hidden; auto-screen, report threshold, admin hide/restore. |
| [sourcing-native.md](sourcing-native.md) | Native supplier listings: lifecycle, fail-closed publish on unknown trust band, rate limits. |
| [sourcing-reco-cache.md](sourcing-reco-cache.md) | Caches and amplification guards for recommendations and similar. |
| [sourcing-reco-history.md](sourcing-reco-history.md) | Price observations, price-history, similar and recommendations endpoints. |
| [sourcing-relevance-qa.md](sourcing-relevance-qa.md) | Kind and condition made searchable (e.g. used production line); relevance fixes. |
| [supplier-analytics.md](supplier-analytics.md) | Privacy-safe supplier analytics: daily per-listing aggregates only, no per-viewer rows. |

## Logistics and geo

| File | Summary |
|---|---|
| [logistics.md](logistics.md) | Landed-cost engine decisions: symmetric range around exact sum of lines, per-stage spreads. |
| [logistics-accuracy.md](logistics-accuracy.md) | Road freight truck-fill billing (>=70% full truck, floor 30%) and other accuracy fixes. |
| [hs-finder.md](hs-finder.md) | HS finder in logistics over a curated HS2022 dataset with Arabic-normalized search. |
| [import-compliance.md](import-compliance.md) | Import-compliance advisor in logistics (`/v1/compliance/*`) reusing duty and incoterm tables. |
| [geo.md](geo.md) | Hub type aliases (land -> land_border, rail, consolidation) added additively. |
| [geo-sea.md](geo-sea.md) | Extended sea-lane graph (~70 nodes) and more sea hubs. |

## Trust

| File | Summary |
|---|---|
| [trust.md](trust.md) | Trust v1: baseline 40 plus weighted signals with saturating curves, hard caps, explainable factors. |
| [trust-file-ownership.md](trust-file-ownership.md) | A media file attached by one supplier is refused for another (`file_in_use`). |
| [trust-persistence.md](trust-persistence.md) | Trust persistence on SQLAlchemy async (`FF_TRUST_DATABASE_URL`). |
| [trust-reviews.md](trust-reviews.md) | rfq review aggregates enter trust as a new `platform_reviews` signal. |
| [trust-scoring-qa.md](trust-scoring-qa.md) | Scoring QA: confidence made monotonic and other fixes. |
| [trust-v2.md](trust-v2.md) | Trust model v2: seven new weighted signals, 0-100 integer confidence, Bayesian shrinkage. |
| [trust-verification-docs.md](trust-verification-docs.md) | Supplier verification documents pipeline; only reviewer-approved docs feed the score. |

## RFQ, deals and payments

| File | Summary |
|---|---|
| [rfq.md](rfq.md) | RFQ basics: money as decimal strings, commission rounded half-up to cents. |
| [rfq-deals-list.md](rfq-deals-list.md) | `GET /v1/deals` matches by user id only, same as deal detail. |
| [rfq-invites.md](rfq-invites.md) | Invite-only private requests: only invited suppliers can offer. |
| [deal-reviews.md](deal-reviews.md) | Reviews live in rfq; gateway routes the two supplier review paths to rfq. |
| [deal-payment-hook.md](deal-payment-hook.md) | Payments -> rfq outbox hook for deal payment status; idempotent, ordered, dead-letter + admin requeue; paid rule. |

## Tracking, notifications and messaging

| File | Summary |
|---|---|
| [tracking.md](tracking.md) | Tracking mock timeline is a deterministic function of reference and time. |
| [tracking-providers.md](tracking-providers.md) | Real tracking providers are UNVERIFIED skeletons, opt-in via `FF_TRACKING_PROVIDER=http`. |
| [tracking-relay.md](tracking-relay.md) | Push relay of tracking outbox to notifications; off unless enabled and configured. |
| [notifications.md](notifications.md) | Watch evaluation: first evaluation only sets the baseline price. |
| [notifications-tracking.md](notifications-tracking.md) | Notifications ingest tracking events by push instead of polling tracking. |
| [notify-delivery.md](notify-delivery.md) | Push and email delivery OFF by default; mock only for tests/dev. |
| [digest-email-verify.md](digest-email-verify.md) | Digest email only to a verified address (6-digit HMAC code, expiry, attempt lock). |
| [messaging.md](messaging.md) | Messaging basics: unread count derived from sequence pointers. |
| [messaging-attachments.md](messaging-attachments.md) | Messages get up to 5 attachments referencing validated media URLs. |
| [media-private.md](media-private.md) | Media files carry public/private visibility; verification files always private with signed URLs. |

## Feed, freight, assistant and demand

| File | Summary |
|---|---|
| [feed.md](feed.md) | New feed service (8113) with real columns and keyset pagination for posts, follows, likes, comments, reports. |
| [feed-antispam.md](feed-antispam.md) | Deterministic Arabic-aware anti-spam (no ML, no network) for posts and comments. |
| [feed-anti-abuse.md](feed-anti-abuse.md) | Feed reports count toward auto-hide only from aged reporters; rate-event rules. |
| [freight.md](freight.md) | New freight-forwarder marketplace service (8114): applications, requests, quotes, ratings, reports. |
| [freight-anti-abuse.md](freight-anti-abuse.md) | Freight rating delay and per-pair caps; other anti-abuse limits. |
| [assistant.md](assistant.md) | Rule-based parser is the source of truth; LLM only refines low-confidence parses. |
| [assistant-llm.md](assistant-llm.md) | `LlmClient` protocol with mock and HTTP (Anthropic Messages shape) adapters; off by default. |
| [assistant-tools-2.md](assistant-tools-2.md) | New intents shipment_status, deal_status, compare, hs_lookup (additive). |
| [assistant-routing-eval.md](assistant-routing-eval.md) | 85-case routing eval fixture; prompt-injection text short-circuits to help; incoterm added to ParsedQuery. |
| [demand-compliance-qa.md](demand-compliance-qa.md) | Demand audit: publisher adapter added (real one OFF), no automatic send path, human approval enforced. |

## Mobile

| File | Summary |
|---|---|
| [mobile.md](mobile.md) | Single agent built mobile core, discover, logistics and profile to keep the contract consistent. |
| [mobile-analytics.md](mobile-analytics.md) | Fire-and-forget deduped listing event reporter; nothing sent in mock mode. |
| [mobile-cards-sensitivity.md](mobile-cards-sensitivity.md) | Assistant chat added to the app (features/assistant, overlay route); card sensitivity rules. |
| [mobile-chat-moderation.md](mobile-chat-moderation.md) | Chat attachments reuse the image picker and media repository; images only, max 5. |
| [mobile-compare.md](mobile-compare.md) | Compare tray as provider state (max 3) on Discover/Search. |
| [mobile-deals.md](mobile-deals.md) | Deal lifecycle UI lives in features/deals; Deal model gains parties and payment status. |
| [mobile-deals-backend.md](mobile-deals-backend.md) | Deals list screen backed by `GET /v1/deals` with role tabs and detail route. |
| [mobile-feed.md](mobile-feed.md) | Feed is a full-screen route linked from Discover, not a sixth tab. |
| [mobile-freight.md](mobile-freight.md) | Freight UI mounted under the Logistics tab (`/logistics/freight/**`). |
| [mobile-fx.md](mobile-fx.md) | FX/carrier UI uses double math with decimal strings on the wire; mode enum mapped client-side. |
| [mobile-invoices.md](mobile-invoices.md) | Invoices UI in features/payments; commission and payment section on the accepted deal. |
| [mobile-live.md](mobile-live.md) | Live repositories follow the OpenAPI contracts (replacing MVP endpoint guesses). |
| [mobile-media-verify.md](mobile-media-verify.md) | image_picker behind an ImagePickService with a fake for tests. |
| [mobile-msg.md](mobile-msg.md) | Messaging/tracking live repositories follow ARCHITECTURE with tolerant JSON parsing. |
| [mobile-notify-shipments.md](mobile-notify-shipments.md) | Shipment alerts deep-link to the tracking detail; unknown rules get a generic icon. |
| [mobile-onboarding.md](mobile-onboarding.md) | Onboarding shown once per launch (later persisted, see mobile-persistence). |
| [mobile-persistence.md](mobile-persistence.md) | shared_preferences for settings, flutter_secure_storage for the refresh token; access token memory-only. |
| [mobile-polish.md](mobile-polish.md) | Settings screen with theme and digit-style keys in the persistence layer. |
| [mobile-privacy.md](mobile-privacy.md) | Privacy and data screen (export and delete) under Settings. |
| [mobile-qa.md](mobile-qa.md) | Live fixtures are real gateway responses (tokens redacted) parsed by tests. |
| [mobile-reco-history.md](mobile-reco-history.md) | Price history, similar and recommendations use only the gateway endpoints. |
| [mobile-reviews.md](mobile-reviews.md) | Reviews UI in features/reviews; summary on supplier screen, write from accepted deal. |
| [mobile-supplier-claim.md](mobile-supplier-claim.md) | Supplier claim UI validates the id pattern client-side; server remains authoritative. |
| [mobile-supplier-products.md](mobile-supplier-products.md) | My products is its own module registered by one line in the router. |
| [mobile-trust-notify.md](mobile-trust-notify.md) | Trust v2 card on the supplier screen (confidence, flags, gaps, history, report sheet). |
| [mobile-verification.md](mobile-verification.md) | Verification documents screen at an overlay route linked from Profile. |
| [mobile-watchlist.md](mobile-watchlist.md) | Watchlist/alerts UI uses only the gateway watchlist and alerts endpoints. |
| [mobile-widget-qa.md](mobile-widget-qa.md) | Static widget QA: mounted guards after awaits and similar fixes. |
| [mobile-ws.md](mobile-ws.md) | ChatSocket interface with live, mock and web-stub implementations. |

## QA, e2e and store

| File | Summary |
|---|---|
| [e2e.md](e2e.md) | e2e boots all services over real HTTP with mock FX and runs scripted steps through the gateway; bugs found. |
| [e2e-extended.md](e2e-extended.md) | Extended e2e boots its own stack with extra env (admin token, report threshold, relay, quota). |
| [contract-e2e.md](contract-e2e.md) | contract_validate runs real service processes through the gateway; e2e extension decisions. |
| [ios-and-store.md](ios-and-store.md) | Platform patching script for generated android/ios folders; store-readiness decisions. |
