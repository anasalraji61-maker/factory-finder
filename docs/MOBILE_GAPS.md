# Mobile gaps audit (2026-10-16)

Read-only audit of `apps/mobile/lib` against CLAUDE.md section 1 and `docs/ROADMAP.md`. Static read only: nothing compiled or run (no Dart SDK). Routes come from `lib/features/module_a|b|c.dart`, `feed/feed_module.dart`, `freight/freight_routes.dart` and `core/router/app_router.dart`. Status: implemented / partial / missing. "Implemented" means the screen, repository and route exist and are covered by mock or contract tests, not that it was verified on a device or a live backend.

## Capability matrix

| Capability | Status | Files | What is missing |
|---|---|---|---|
| Search products / materials / production lines, new + used | implemented | `discover/screens/search_screen.dart`, `discover/data/search_facets.dart`, `discover/data/discover_models.dart` (`ListingKind`, condition) | Verify facets cover production line and used on the live API. Results are 165 mock listings (backend Phase 4). |
| Supplier trust score view | implemented | `trust/trust_widgets.dart`, `core/widgets/trust_badge.dart`, `discover/screens/supplier_screen.dart`, `reviews/screens/reviews_list_screen.dart` | Only as good as the mock trust data. |
| Landed cost to buyer's city | implemented | `logistics/screens/calculator_screen.dart`, `results_screen.dart`, `sensitivity_section.dart`, `hs_picker.dart`, `fx/`, `carriers/` | Not wired from a listing or deal into a pre-filled quote with a buyer city. Static duty and freight tables, estimates only (backend). |
| Freight forwarder compare / award | implemented | `freight/` (create request, quote comparison, accept, forwarder apply and inbox) | Awarded quote returns to the calculator as an override only if the user navigates back manually. No forwarder chat or contact path. |
| Shipment tracking | partial | `tracking/` (list, detail, add sheet, validators) | Reachable only from the Logistics tab. No link from a deal, no push on a status change (push is a no-op), providers are skeletons. |
| RFQ reverse marketplace with offers | partial | `requests/` (create, list, detail with offers, accept). Only `POST /v1/requests`, `GET /offers`, `POST /offers/:id/accept` exist in `rfq_repository.dart` | Seller side is absent: no browse of open or invited requests, no create-offer screen, no counter-offer or withdraw. Only the buyer half exists. |
| Messaging | implemented | `messages/` (REST + WebSocket, attachments, block, mute) | No push when offline, no typing indicator, no read receipts. |
| Alerts (price drop, watchlist) | partial | `watchlist/`, `notify_prefs/`, `notify_prefs/push_registration.dart` | `NoopPushTokenSource` is the only implementation. No `firebase_messaging` in `pubspec.yaml`, so no real push. In-app alerts list only. |
| Arabic assistant | implemented | `assistant/` (cards, routes to listings and tracking) | Entry sits only under the Logistics tab tools, not on Discover. No voice input. |
| Social feed | implemented | `feed/` (posts, follow, mute, composer gated to suppliers) | Entry is an icon on the Discover header only. Not a tab. |
| Deals / payments with commission | partial | `deals/`, `payments/` (invoice, USDT, `commission` invoice kind, cancel) | Deal-to-tracking link missing. Payments are mock and USDT-TRC20 only. No card payments, no QR or wallet deep link (no `url_launcher`). No receipt export. |
| Supplier claim / verification | implemented | `supplier_claim/`, `trust/verification_screen.dart`, `verification_form_sheet.dart`, `my_products/` | PDF decision is open (STATUS). Images only via `image_picker`, no `file_picker`. |
| Settings / privacy / account deletion | implemented | `settings/`, `privacy/` (export, delete), `auth/password_screens.dart` | Export result has no save or share path (no `share_plus` or `path_provider` in `pubspec.yaml`). No in-app link to the privacy policy or terms (drafts only). |
| Onboarding | implemented | `onboarding/` | No language or country or city capture feeding the calculator default (needs check). |
| Demand matching (Phase 5) | missing in app | none | Backend only, admin console only. Acceptable for now. |

## Cross-cutting gaps

- `android/` and `ios/` platform folders are not committed, so the app has never been built or run on a device. The Flutter code has never been compiled locally (STATUS).
- `FF_MOCK` defaults to true (`core/api/api_client.dart`). Live repositories exist but have not run against a live backend (`test/live`, `test/live_contract`).
- No crash reporting, analytics SDK or deep-link configuration (`app_links`, `url_launcher`) in `pubspec.yaml`.
- Phases 4 and 6 (real data, store release) block every "implemented" item from being real.

## Top 10 gaps by user value

1. **Seller side of the RFQ marketplace.** No browse of open or invited requests, no create-offer, no withdraw. Without it the reverse marketplace has no supply and nothing reaches deals. (`requests/`, `rfq_repository.dart`)
2. **No runnable build.** Missing `android/` and `ios/` folders, never compiled, no device test. Nothing ships until this is fixed. (`apps/mobile/`, STATUS P0)
3. **Real push notifications.** `firebase_messaging` is absent, so price alerts, chat messages, shipment updates and offers cannot reach a closed app. (`notify_prefs/push_registration.dart`, `pubspec.yaml`)
4. **Live backend validation.** Default is mock mode, and no live smoke has run against a deployed gateway. First task: run `test/live_contract` against `make dev`. (`api_client.dart`, `test/live*`)
5. **Listing to landed cost in one tap.** Wire a listing or supplier to a pre-filled quote using the buyer's saved city. This is the core promise of the product. (`discover/screens/listing_detail_screen.dart`, `logistics/data/quote_request.dart`)
6. **Deal to shipment flow.** Create a shipment from a deal and show tracking status on the deal screen, then notify the buyer. Closes the order-to-delivery loop. (`deals/screens/deal_detail_screen.dart`, `tracking/`)
7. **Payment UX hardening.** Add a wallet deep link and QR for USDT, a receipt share or export, and a commission breakdown visible to the supplier. Needed before the first paid commission (Phase 6). (`payments/screens/invoice_screen.dart`, needs `url_launcher`)
8. **Assistant and feed discoverability.** Assistant lives under Logistics tools and the feed behind a header icon. Put the assistant on Discover or as a floating entry, since it is the strongest Arabic-first feature. (`logistics_screen.dart`, `feed_screen.dart`)
9. **Data export and legal links.** Export has no save or share path, and no in-app privacy or terms screens (drafts exist). Required for store review. (`privacy/privacy_screen.dart`, `docs/PRIVACY_POLICY.draft.md`)
10. **Verification document upload for PDFs and trust-file previews.** Images only. Decide the PDF policy and add `file_picker`. Suppliers often hold PDF certificates. (`trust/verification_form_sheet.dart`)

Not mobile work: real supplier data, real freight rates, USA and Europe origins (Phase 4) and card payments (UK company, Phase 6).
