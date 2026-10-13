# Factory Finder mobile app (`factory_finder`)

Flutter app (Android + iOS), Arabic-first (RTL) with English as the second language.
Runs entirely in **mock mode** by default: no backend is needed.

## What is in the MVP slice

| Tab | Route | Status |
|---|---|---|
| Discover | `/discover`, `/discover/search?q=` | feed, trending, kind/category chips, search, filters + sort |
| Listing / Supplier | `/listing/:id`, `/supplier/:id` | detail, trust factors sheet, supplier page |
| Requests | `/requests` | placeholder ("coming soon") |
| Messages | `/messages` | placeholder |
| Logistics | `/logistics`, `/logistics/calculator?listing_id=`, `/logistics/results` | landed-cost calculator + comparison results |
| Profile | `/profile` | language, display currency, default destination, theme |

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

## Layout

```
lib/core/        models, api client, providers, theme, i18n, router, shared widgets
lib/shell/       bottom-tab shell
lib/features/    module_a.dart (discover, requests), module_b.dart (logistics, messages), profile/
test/            model/enum/money, i18n, mock quote generator, mock filters, widget smoke test
```

Features plug in through `FeatureModule` (`lib/core/registry/feature_module.dart`).
All user-facing strings live in `*_strings.dart` files as `key: (arabic, english)` pairs.

## Test

```bash
flutter analyze
flutter test
```
