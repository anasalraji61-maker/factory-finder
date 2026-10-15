# Factory Finder mobile app (`factory_finder`)

Flutter app (Android + iOS), Arabic-first (RTL) with English as the second language.
Runs entirely in **mock mode** by default: no backend is needed.

## What is in the MVP slice

| Tab | Route | Status |
|---|---|---|
| Discover | `/discover`, `/discover/search?q=` | feed, trending, kind/category chips, search, filters + sort |
| Listing / Supplier | `/listing/:id`, `/supplier/:id` | detail, trust factors sheet, supplier page |
| Business verification | `/verification` | supplier documents, status chips, submit/withdraw; public level badge on supplier and listing screens |
| Requests & Offers | `/requests`, `/requests/new?supplier=<id>&supplier_name=<name>`, `/requests/:id` | my/open requests, create form, offers, accept -> deal summary (commission). Invite-only RFQs: the supplier profile has a 'Request a quote from this supplier' action that opens the create form with that supplier pre-added as an invitee; the form shows a removable 'Invited suppliers' chip list (max 50, only they can see the request) and sends `invited_supplier_ids`; the buyer's request detail shows an 'Invite-only' pill |
| Messages | `/messages`, `/chat/:id`, `/settings/privacy/blocked` | conversation list + chat (`contracts/openapi/messaging.yaml`). Long-press a conversation for Mute / Archive (archive shows an Undo snackbar); the app-bar archive icon toggles the 'Archived' filter (`GET /v1/conversations?archived=true`); muted rows show a bell-off icon and a grey badge. `PUT /v1/conversations/{id}/preferences {muted?, archived?}`. The Messages tab icon shows an unread badge from `GET /v1/conversations/unread-total` (muted and archived excluded; refreshed with the list and on tab tap). Chat overflow menu: Block user / Unblock with a confirm dialog (`PUT/DELETE /v1/blocks/{user_id}`; after blocking the chat closes and the thread disappears). Settings -> Privacy & data -> 'Blocked users' lists `GET /v1/blocks` (user ids only, the contract has no names) and unblocks. `user_blocked` (422 when starting a chat with someone you blocked) is localized in `lib/core/i18n/error_messages.dart`; a blocked sender gets the neutral 404 `conversation_not_found`, nothing special in the app. Mock repo supports all of it. Code: `lib/features/messages/`, tests: `test/messages/conversation_prefs_blocks_test.dart`, `test/widgets/conversation_manage_test.dart` |
| Logistics | `/logistics`, `/logistics/calculator?listing_id=`, `/logistics/results` | landed-cost calculator + comparison results |
| Freight quotes | `/logistics/freight`, `/logistics/freight/new`, `/logistics/freight/requests/:id`, `/logistics/freight/forwarder/apply`, `/logistics/freight/forwarder/requests/:id` | forwarder marketplace (`contracts/openapi/freight.yaml`): buyer requests + ranked quote comparison, accept / complete / rate, forwarder application, inbox, quote submit / revise / withdraw, abuse reports. Code in `lib/features/freight/` |
| Profile | `/profile`, `/settings` | profile: sign in/out, server URL, shortcuts; settings: language, theme (light/dark/system), display currency, default destination, digit style |
| Auth | `/login`, `/register`, `/forgot-password`, `/reset-password?token=`, `/settings/change-password` | gateway auth (tokens in memory, Bearer + one refresh on 401). Password recovery: 'Forgot password?' on the login screen -> email form that always shows the same neutral confirmation -> reset screen (paste token + new password + confirm, min 8 chars like registration). 'Change password' tile in Settings when signed in; the `POST /v1/me/password` response (fresh token pair for this device, the server revokes all other refresh tokens) is stored via the token store. 'Sign out of all devices' tile in Settings (confirm dialog, `POST /v1/auth/logout-all`, any 2xx = success, 401 = already signed out, other errors keep you signed in with a snackbar; then the normal local sign-out). 401 handling: one refresh attempt per request, retry once; a rejected refresh (4xx other than 429) clears the session, offline/5xx/429 keeps it; no loops. Calls `POST /v1/auth/password/forgot`, `/v1/auth/password/reset`, `/v1/me/password` (shapes assumed from the gateway agent; `contracts/openapi/gateway.yaml` did not yet contain them when written, re-check). 429 / 422 and the codes `rate_limited`, `invalid_token`, `invalid_current_password`, `weak_password` are localized in `lib/core/i18n/error_messages.dart` (`localizedPasswordError`). Mock mode accepts anything except token `invalid-token`, current password `wrong-password`, and email `limited@example.com` (429). Code: `lib/features/auth/password_*.dart` |

## Run

The platform folders are not checked in. Generate them once:

```bash
cd apps/mobile
flutter create . --platforms=android,ios --project-name factory_finder
flutter pub get
flutter run --dart-define=FF_MOCK=true
```

## Environment (compile-time `--dart-define`)

| Name | Default | Meaning |
|---|---|---|
| `FF_MOCK` | `true` | use in-app fixtures instead of the backend |
| `FF_API_BASE_URL` | `http://10.0.2.2:8000` | gateway URL when `FF_MOCK=false` |

## Live mode (`FF_MOCK=false`)

```bash
flutter run --dart-define=FF_MOCK=false --dart-define=FF_API_BASE_URL=http://10.0.2.2:8000
```

All repositories call the gateway with the contract paths: `GET /v1/search`, `/v1/listings/{id}`,
`/v1/suppliers/{id}`, `/v1/trust/suppliers/{id}`, `/v1/categories`, `POST /v1/quotes/landed-cost`,
`/v1/requests` (`scope=mine|public`), `/v1/requests/{id}/offers`, `POST /v1/offers/{id}/accept`,
`/v1/auth/*`. `ApiClient` keeps access/refresh tokens in memory, sends `Authorization: Bearer`,
refreshes once on 401 and maps errors to `ApiException(status, code, message)`.
The server URL can be changed at runtime from Profile (persisted). In a **release** build that was
built with an explicit `FF_API_BASE_URL`, the stored override is ignored and the editor is hidden
unless the build also passes `--dart-define=FF_ALLOW_SERVER_URL=true` (developer toggle).

## Release builds

`FF_MOCK` defaults to `true` (dev/CI). A release build still in mock mode paints a **MOCK DATA**
banner so it cannot ship silently. Always build releases with:

```bash
flutter build apk --release --dart-define=FF_MOCK=false --dart-define=FF_API_BASE_URL=https://api.example.com
```

Chat uses a single-use WebSocket ticket (`POST /v1/ws-ticket`, `?ticket=`) so the access token never
appears in a URL; against an older gateway it falls back to `?token=`. The Cairo font is bundled
(`assets/fonts`, OFL) - no runtime font download.

## Layout

```
lib/core/        models, api client, providers, theme, i18n, router, shared widgets
lib/shell/       bottom-tab shell
lib/features/    module_a.dart (discover, requests, auth), module_b.dart (logistics, messages), profile/, requests/, auth/
test/            core, discover, logistics, requests (models/filters/validators), live (fake Dio adapter, auth refresh)
```

Features plug in through `FeatureModule` (`lib/core/registry/feature_module.dart`).
All user-facing strings live in `*_strings.dart` files as `key: (arabic, english)` pairs.

## Offline read cache

`lib/core/storage/read_cache.dart` keeps a small read cache on the settings
store (shared_preferences in the app, `MemoryStore` in tests) for exactly two
public things: the last successful search results (up to 5 recent queries,
matched by exact query) and the first page of the signed-in user's home feed
(per user id; per-viewer `viewer_liked` is dropped; never cached when signed
out or for later pages). Entries expire after 24 h and a slot is capped at
200,000 characters (oldest evicted; an oversized entry is skipped).

The cache is read only when the network call fails with no HTTP status
(`isNetworkError`: socket / DNS / timeout). Server errors (4xx/5xx) are never
masked. Served pages carry `fromCache = true` and the screens show the
existing offline banner plus a "showing saved results" line
(`offline.saved_note`). Auth, deals, chats, invoices, verification and every
other private repository are not cached. The slots are removed on account
deletion. Tests: `test/core/read_cache_test.dart`,
`test/core/offline_cache_test.dart`, `test/widgets/offline_saved_test.dart`.

## Test

```bash
flutter analyze
flutter test
```

## Messages and shipment tracking (`mobile-msg`)

- `lib/features/messages/`: conversations list (unread badge, listing/request chip), chat (RTL bubbles, date separators, system messages, optimistic send with tap-to-retry, 4 s polling as the realtime fallback), new conversation (`/messages/new?supplier_id=&listing_id=`, opens `/chat/<id>`). Live repository uses `/v1/conversations*`; mock has 8 Arabic conversations.
- `lib/features/tracking/`: `/logistics/tracking` (list with progress + status chips, add-shipment sheet with client-side ISO 6346 container, AWB mod-7, IMO and B/L checks) and `/logistics/tracking/:id` (route progress header, vertical timeline, refresh). Live repository uses `/v1/shipments*`; mock has 5 shipments in different stages.
- Tests: `test/messages/`, `test/tracking/`.

## Assistant cards and cost sensitivity
- `/assistant` (Logistics tools list): chat with `POST /v1/assistant/query`; renders `cards[]` (shipment_status, deal_status, listing_comparison, hs_code, notice; unknown types shown generically), maps 429 to an ar/en message. Mock mode returns sample cards.
- Calculator results show quote-level `warnings` and a collapsible "what if" section from the optional per-option `sensitivity` bands.

## Forwarder quote in landed cost

On an awarded freight request the quote card has "Use this quote in landed cost". It calls
`GET /v1/freight/quotes/{id}/landed-cost-input` (owner only, 409 `quote_not_awarded`), then opens
`/logistics/calculator` prefilled with the shipment origin/destination and the returned
`freight_override` (shown as a removable banner). `POST /v1/quotes/landed-cost` then carries
`freight_override` (+ `mode_family`). Result lines with `quoted: true` get a "Forwarder quote" pill,
an exact amount (no range) and the quote's valid-until date; every other line keeps the Estimate label.
An expired override is ignored by the backend, which adds an assumption note (shown in Assumptions).
Mock mode mirrors this (`MockFreightRepository.landedCostInput`, `MockQuoteGenerator`).
Tests: `test/logistics/freight_override_test.dart`, `test/freight/landed_cost_flow_test.dart`.

## Bulk product import (My products)

Route `/my-products/import` (upload icon in the My products app bar) lets a
verified supplier paste CSV and call `POST /v1/my/listings/import`.

- Header row required. Required columns: `external_ref`, `title`, `category`,
  `price_min`, `country`. Optional: `title_ar`, `description`, `description_ar`,
  `price_max` (defaults to `price_min`), `currency` (USD), `unit` (piece),
  `moq` (1), `kind` (product), `condition` (new), `incoterm`, `unit_weight_kg`,
  `unit_volume_m3`, `hs_code`, `lead_time_min`, `lead_time_max`, `images`
  (URLs separated by `|`), `city`. Comma, tab or semicolon delimited.
- `lib/features/my_products/import/import_logic.dart` holds the pure-Dart CSV
  parser (quotes, `""`, newlines in quotes, CRLF, BOM, Arabic text/digits) and
  per-row validation (reuses `validateProductDraft`). Invalid rows are shown
  with the failing column and are never sent.
- Dry run first (nothing saved), then Import. The server accepts 100 items per
  request, so larger pastes are sent in batches of 100 (up to 1000 rows); the
  screen announces the batch count and keeps partial results if a batch fails.
- Mock mode: `MockMyListingsBackend.importItems` is idempotent on `external_ref`.
- Tests: `test/my_products/import_test.dart`, `test/widgets/import_products_test.dart`.
