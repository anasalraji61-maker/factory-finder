# Factory Finder mobile app (`factory_finder`)

Flutter app (Android + iOS), Arabic-first (RTL) with English as the second language.
Runs entirely in **mock mode** by default: no backend is needed.

## What is in the MVP slice

| Tab | Route | Status |
|---|---|---|
| Discover | `/discover`, `/discover/search?q=` | feed, trending, kind/category chips, search, filters + sort |
| Listing / Supplier | `/listing/:id`, `/supplier/:id` | detail, trust factors sheet, supplier page |
| Business verification | `/verification` | supplier documents, status chips, submit/withdraw; public level badge on supplier and listing screens |
| Requests & Offers | `/requests`, `/requests/new`, `/requests/:id` | my/open requests, create form, offers, accept -> deal summary (commission) |
| Messages | `/messages` | placeholder |
| Logistics | `/logistics`, `/logistics/calculator?listing_id=`, `/logistics/results` | landed-cost calculator + comparison results |
| Freight quotes | `/logistics/freight`, `/logistics/freight/new`, `/logistics/freight/requests/:id`, `/logistics/freight/forwarder/apply`, `/logistics/freight/forwarder/requests/:id` | forwarder marketplace (`contracts/openapi/freight.yaml`): buyer requests + ranked quote comparison, accept / complete / rate, forwarder application, inbox, quote submit / revise / withdraw, abuse reports. Code in `lib/features/freight/` |
| Profile | `/profile`, `/settings` | profile: sign in/out, server URL, shortcuts; settings: language, theme (light/dark/system), display currency, default destination, digit style |
| Auth | `/login`, `/register` | gateway auth (tokens in memory, Bearer + one refresh on 401) |

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
The server URL can be changed at runtime from Profile (memory only).

## Layout

```
lib/core/        models, api client, providers, theme, i18n, router, shared widgets
lib/shell/       bottom-tab shell
lib/features/    module_a.dart (discover, requests, auth), module_b.dart (logistics, messages), profile/, requests/, auth/
test/            core, discover, logistics, requests (models/filters/validators), live (fake Dio adapter, auth refresh)
```

Features plug in through `FeatureModule` (`lib/core/registry/feature_module.dart`).
All user-facing strings live in `*_strings.dart` files as `key: (arabic, english)` pairs.

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
