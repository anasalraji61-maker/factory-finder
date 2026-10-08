# Agents — roster, ownership, interfaces

The orchestrator (architect) splits work into **waves**. In a build wave all builders run in parallel; then QA agents verify; then fixes; then the orchestrator commits and pushes.

## Global rules for every agent (in addition to CLAUDE.md)

- **Never run git commands.** The orchestrator owns commits and pushes.
- **Write only inside the paths you own** (table below). Your decisions go in `docs/decisions/<your-agent-id>.md` (create it). Requests for other modules go in `docs/requests/<your-agent-id>-<topic>.md`.
- Python: use the shared venv: `cd services/<name> && ../../.venv/bin/python -m pytest -q`. Lint: `.venv/bin/ruff check services/<name>`. Do not create other venvs. Install an extra package only if essential: `.venv/bin/pip install <pkg>` and list it in your `pyproject.toml`.
- Each `pyproject.toml` must contain:
  ```toml
  [tool.pytest.ini_options]
  pythonpath = ["src"]
  testpaths = ["tests"]
  addopts = "--import-mode=importlib -q"
  asyncio_mode = "auto"
  ```
- Calls to other services go through `clients/` (Protocol + httpx implementation + mock). Tests use the mock — never the network.
- The Flutter SDK is **not available** in the build sandbox (CI on GitHub runs `flutter analyze` + `flutter test`). Mobile agents must therefore write code exactly against the interfaces in §Mobile contract, use only the packages listed there, avoid code generation, and re-read their files for syntax/type errors before finishing.
- Finish with a short report: what you built, files/dirs, test command + result, known gaps.

## Roster & ownership (wave 1)

| Agent id | Owns (write access) | Scope |
|---|---|---|
| `gateway` | `services/gateway/`, `contracts/openapi/gateway.yaml` | Auth (register/login/refresh, JWT, bcrypt), users & profile (name, phone, email, company, role buyer/supplier/both, default destination, currency, language), reverse-proxy of `/v1/*` paths to services by prefix (config map), `/v1/home` aggregation (mockable), CORS, request id, rate limit (in-memory) |
| `sourcing` | `services/sourcing/`, `contracts/openapi/sourcing.yaml` | Source adapters (rich mock catalog ≥ 120 listings: products, raw materials, production lines new & used; origins CN-heavy + US, DE, IT, TR, IN, VN; Arabic titles), adapter registry, concurrent fan-out with timeouts, normalization, de-dup, ranking, filters, pagination, categories tree (bilingual), TTL cache; real adapter stubs (alibaba, made_in_china, aliexpress, source_1688) disabled by default and compliant with CLAUDE.md rule 6 |
| `logistics` | `services/logistics/`, `contracts/openapi/logistics.yaml` | Landed-cost engine per ARCHITECTURE §5 (all modes, chargeable weight, container fitting, incoterm-aware stages, duties/VAT tables for ≥ 25 destination countries incl. IQ, TR, IR, SY, JO, SA, AE, KW, EG, US, DE, FR, GB…, rate tables for main lanes from CN/US/EU), FX adapter (mock + free public provider, cached), carriers/forwarders directory (mock), warnings (embargo/sanctions lanes flagged, oversize, DG). Uses geo through `clients/geo.py` |
| `geo` | `services/geo/`, `contracts/openapi/geo.yaml` | Bundled datasets: ~60 countries (name en/ar, currency, region), ≥ 300 major cities with coordinates (all Iraqi governorate capitals + major industrial cities of CN/US/EU/TR/IR/gulf), ≥ 120 hubs (sea ports with UN/LOCODE, cargo airports IATA, land border crossings e.g. Ibrahim Khalil, Trebil, Safwan, Arar, Al-Qaim, Kapıkule, Khorgos/Alashankou rail), nearest-hub search, distance (haversine × road factor by country; sea distance via waypoint approximation table for major lanes) |
| `trust` | `services/trust/`, `contracts/openapi/trust.yaml` | Explainable trust score: signals (years in business, verification/audit, transactions, response rate, ratings & reviews count, disputes, certifications ISO/CE, domain age, contact consistency, sanctions-list hit stub, price outlier vs market median), weights in config, bands, bilingual explanations, data adapter (mock signals for every mock supplier id `sup_*` from sourcing's catalog pattern), cache |
| `rfq` | `services/rfq/`, `contracts/openapi/rfq.yaml` | Requests (kind, title, description, quantity, unit, target price, destination, deadline, attachments urls, status open/negotiating/awarded/closed/expired), offers (price, moq, lead time, incoterm, validity, notes, supplier ref), accept → Deal with commission (config % by kind, min fee), status machine with tests, matching suggestions via `clients/sourcing.py`, pagination, ownership checks by `X-User-Id` |
| `messaging` | `services/messaging/`, `contracts/openapi/messaging.yaml` | Conversations (participants, context: listing/request/deal), messages (text, attachment url, system events), unread counts, read receipts, cursor pagination, WebSocket broadcast per conversation (in-process hub), basic content safety (block phone-number harvesting spam patterns is NOT needed; do block obvious abuse words list + max length) |
| `tracking` | `services/tracking/`, `contracts/openapi/tracking.yaml` | Reference validation (ISO 6346 container check digit, AWB mod-7 check, IMO check digit, B/L basic), shipments CRUD per user, provider adapters (mock generating a realistic deterministic event timeline from origin port to destination with vessel name & ETA; real provider stubs), normalized statuses (booked, gate_in, loaded, departed, transshipment, arrived, discharged, customs_hold, released, out_for_delivery, delivered), refresh with throttling |
| `notifications` | `services/notifications/`, `contracts/openapi/notifications.yaml` | Watchlist (listing id or saved search + target price), rule evaluation (price drop %, below target, cheaper equivalent supplier found) using `clients/sourcing.py`, alerts inbox, device tokens, push adapter (mock + FCM stub), dedupe/cooldown |
| `assistant` | `services/assistant/`, `contracts/openapi/assistant.yaml` | Arabic/English natural-language query → intent (search, quote, trust, track) + structured query (kind, condition, quantity, unit, budget, origin pref, destination city/country) using a deterministic rule-based parser (Arabic + Iraqi dialect keywords, numbers in Arabic-Indic digits) with optional `llm` adapter (mock default); orchestrates sourcing + logistics + trust via clients; composes a concise Arabic answer |
| `infra` | `infra/`, `.github/`, `Makefile`, `docker-compose.yml`, `.env.example`, `ruff.toml`, `scripts/`, root `README.md` dev section only below the marker `<!-- DEV -->` | docker-compose (postgres, redis, all services), generic service Dockerfile, Makefile (`dev`, `test`, `lint`, `test-<svc>`), GitHub Actions: backend matrix (ruff + pytest per service), mobile (subosito/flutter-action stable: `flutter create . --platforms=android,ios --org com.factoryfinder` if `android/` missing, `flutter pub get`, `flutter analyze --no-fatal-infos --no-fatal-warnings`, `flutter test`), contracts validation (`scripts/validate_contracts.py`) |
| `mobile-core` | `apps/mobile/pubspec.yaml`, `apps/mobile/analysis_options.yaml`, `apps/mobile/README.md`, `apps/mobile/lib/main.dart`, `apps/mobile/lib/app.dart`, `apps/mobile/lib/core/**`, `apps/mobile/lib/shell/**`, `apps/mobile/lib/features/profile/**`, `apps/mobile/test/core/**`, `apps/mobile/test/profile/**` | Everything in §Mobile contract owned by core: theme (beautiful, modern, social-commerce look), router + shell with 5 tabs, i18n system, models, API client + mock switch, shared widgets, providers, Profile tab (account card, language switch ar/en, display currency, default destination country/city picker, watchlist entry placeholder, about) |
| `mobile-features-a` | `apps/mobile/lib/features/module_a.dart`, `apps/mobile/lib/features/discover/**`, `apps/mobile/lib/features/listing/**`, `apps/mobile/lib/features/requests/**`, `apps/mobile/test/features_a/**` | Discover (search bar, kind tabs: منتجات / مواد أولية / خطوط إنتاج, trending feed, filters sheet, results), listing detail, supplier page with trust factors, Requests & Offers (list, create, detail with offers, accept) — with rich mock fixtures |
| `mobile-features-b` | `apps/mobile/lib/features/module_b.dart`, `apps/mobile/lib/features/logistics/**`, `apps/mobile/lib/features/messages/**`, `apps/mobile/test/features_b/**` | Logistics hub (landed-cost calculator form + results comparison with recommended option, stacked cost bar, expandable lines, transit days, warnings; FX rates & converter; carriers list; shipments tracking list/add/detail timeline), Messages (conversation list with unread, chat screen, new conversation from supplier/listing) — with rich mock fixtures |

## Wave 2 — QA (after builders finish)

| Agent id | Scope |
|---|---|
| `qa-backend` | Run every service's tests + ruff; review for rule violations (money as float, secrets, network in tests, cross-module imports, contract mismatch); **fix in place**; add missing edge-case tests |
| `qa-contracts` | Validate all OpenAPI files; check every implemented route matches its contract and the gateway proxy map; check common schema usage; fix in place |
| `qa-mobile` | Static review of all Dart code against §Mobile contract (imports, names, signatures, null-safety, const misuse, RTL, i18n keys present in both ar/en); fix in place; after push, read GitHub Actions `flutter analyze` logs via `gh` and fix |

---

## Mobile contract (exact Dart interfaces — all mobile agents code against these)

Package: `factory_finder` (imports look like `package:factory_finder/core/...`). Dart SDK `>=3.4.0 <4.0.0`.

**Allowed dependencies** (core puts all of them in `pubspec.yaml`; features may use only these):
```yaml
dependencies:
  flutter: {sdk: flutter}
  flutter_localizations: {sdk: flutter}
  flutter_riverpod: ^2.5.1
  go_router: ^14.2.0
  dio: ^5.4.3
  intl: any
  cached_network_image: ^3.3.1
  shimmer: ^3.0.0
  google_fonts: ^6.2.1
dev_dependencies:
  flutter_test: {sdk: flutter}
  flutter_lints: ^4.0.0
```

### Owned by mobile-core

`lib/core/registry/feature_module.dart`
```dart
import 'package:go_router/go_router.dart';

class FeatureModule {
  const FeatureModule({
    this.branchRoutes = const {},
    this.overlayRoutes = const [],
    this.strings = const {},
  });

  /// Routes inside bottom tabs. Keys: 'discover' | 'requests' | 'messages' | 'logistics'.
  /// The FIRST route in each list must be the tab root: '/discover', '/requests', '/messages', '/logistics'.
  final Map<String, List<RouteBase>> branchRoutes;

  /// Full-screen routes shown above the shell (top-level in GoRouter), e.g. '/listing/:id', '/chat/:id'.
  final List<RouteBase> overlayRoutes;

  /// {'ar': {'discover.title': 'استكشف'}, 'en': {'discover.title': 'Discover'}}
  final Map<String, Map<String, String>> strings;
}
```
The router (`lib/core/router/app_router.dart`) imports `package:factory_finder/features/module_a.dart` (`featureModuleA`) and `package:factory_finder/features/module_b.dart` (`featureModuleB`), builds a `StatefulShellRoute.indexedStack` with branches in order discover, requests, messages, logistics, profile, and adds both modules' `overlayRoutes` at top level. Profile root `/profile` is core's own. Initial location `/discover`. Core registers both modules' `strings` at startup.

`lib/core/i18n/tr.dart`
```dart
import 'package:flutter/widgets.dart';
class AppStrings {
  static void register(Map<String, Map<String, String>> tables);   // merge
  static String lookup(String languageCode, String key, [Map<String, String> args = const {}]);
}
extension TrX on BuildContext {
  /// Returns the string for the current locale (fallback: en, then the key). Replaces {name} placeholders with args.
  String tr(String key, [Map<String, String> args = const {}]);
}
```

`lib/core/api/api_client.dart`
```dart
final apiClientProvider = Provider<ApiClient>((ref) => ApiClient.fromEnvironment());
class ApiClient {
  ApiClient({required this.baseUrl, required this.isMock});
  factory ApiClient.fromEnvironment(); // FF_API_BASE_URL (default http://10.0.2.2:8000), FF_MOCK (default true)
  final String baseUrl;
  final bool isMock;
  Future<dynamic> get(String path, {Map<String, dynamic>? query});
  Future<dynamic> post(String path, {Object? body});
  Future<dynamic> patch(String path, {Object? body});
  Future<dynamic> delete(String path);
}
class ApiException implements Exception {
  ApiException({this.status, required this.code, required this.message});
  final int? status; final String code; final String message;
}
/// Simulated latency for mock repositories.
Future<void> mockDelay([int milliseconds = 350]);
```
Repositories live in each feature, take `ApiClient`, and when `api.isMock` return their own fixtures after `mockDelay()`.

`lib/core/models/models.dart` (single file, hand-written `fromJson`/`toJson`; JSON keys snake_case, Dart fields camelCase)
```dart
enum ListingKind { product, rawMaterial, productionLine }          // json: product | raw_material | production_line
enum ItemCondition { brandNew, used, refurbished }                  // json: new | used | refurbished
enum TransportMode { seaLcl, seaFcl20, seaFcl40, seaFcl40hc, air, rail, road } // json: sea_lcl ...
enum Incoterm { exw, fca, fob, cfr, cif, dap, ddp }                 // json: EXW ...
enum TrustBand { green, yellow, red, unknown }
// every enum above has:  String get json;   and a top-level parser:  ListingKind listingKindFromJson(String s) etc.
// parsers: listingKindFromJson, itemConditionFromJson, transportModeFromJson, incotermFromJson, trustBandFromJson

class Money { const Money({required this.amount, required this.currency}); final String amount; final String currency;
  double get value; String format(); factory Money.fromJson(Map<String, dynamic> j); Map<String, dynamic> toJson(); }
class MoneyRange { const MoneyRange({required this.min, required this.max}); final Money min; final Money max; String format(); fromJson/toJson }
class DayRange { const DayRange({required this.min, required this.max}); final int min; final int max; fromJson/toJson }
class GeoPoint { const GeoPoint({required this.lat, required this.lon}); final double lat; final double lon; fromJson/toJson }
class Location { const Location({required this.countryCode, this.city, this.point}); final String countryCode; final String? city; final GeoPoint? point; fromJson/toJson }
class SupplierSummary { const SupplierSummary({required this.id, required this.name, required this.location, this.yearsInBusiness, this.verified = false, this.trustScore, this.trustBand = TrustBand.unknown});
  final String id; final String name; final Location location; final int? yearsInBusiness; final bool verified; final int? trustScore; final TrustBand trustBand; fromJson/toJson }
class Listing { const Listing({required this.id, required this.source, required this.kind, required this.title, required this.price, required this.supplier,
  this.sourceUrl, this.condition = ItemCondition.brandNew, this.titleAr, this.category, this.images = const [], this.unit = 'piece', this.moq,
  this.incoterm, this.unitWeightKg, this.unitVolumeM3, this.hsCode, this.leadTimeDays, this.origin});
  final String id; final String source; final String? sourceUrl; final ListingKind kind; final ItemCondition condition; final String title; final String? titleAr;
  final String? category; final List<String> images; final MoneyRange price; final String unit; final int? moq; final Incoterm? incoterm;
  final double? unitWeightKg; final double? unitVolumeM3; final String? hsCode; final DayRange? leadTimeDays; final SupplierSummary supplier; final Location? origin;
  String displayTitle(String languageCode); fromJson/toJson }
class CostLine { const CostLine({required this.stage, required this.description, required this.amount, required this.estimate, this.source, this.fxRate});
  final String stage; final String description; final Money amount; final bool estimate; final String? source; final String? fxRate; fromJson/toJson }
class LandedCostOption { const LandedCostOption({required this.mode, required this.lines, required this.total, required this.transitDays,
  this.originHub, this.destinationHub, this.routeSummary, this.co2Kg, this.recommended = false, this.warnings = const []});
  final TransportMode mode; final List<CostLine> lines; final MoneyRange total; final DayRange transitDays; final String? originHub; final String? destinationHub;
  final String? routeSummary; final double? co2Kg; final bool recommended; final List<String> warnings; fromJson/toJson }
class LandedCostQuote { const LandedCostQuote({required this.id, required this.currency, required this.options, required this.createdAt, this.origin, this.destination, this.assumptions = const []});
  final String id; final String currency; final List<LandedCostOption> options; final DateTime createdAt; final Location? origin; final Location? destination; final List<String> assumptions; fromJson/toJson }
class TrustFactor { const TrustFactor({required this.key, required this.impact, required this.explanation, this.explanationAr});
  final String key; final int impact; final String explanation; final String? explanationAr; fromJson/toJson }
class TrustScore { const TrustScore({required this.supplierId, required this.score, required this.band, required this.factors});
  final String supplierId; final int score; final TrustBand band; final List<TrustFactor> factors; fromJson/toJson }
class PageResult<T> { const PageResult({required this.items, required this.total, required this.page, required this.pageSize});
  final List<T> items; final int total; final int page; final int pageSize;
  static PageResult<T> fromJson<T>(Map<String, dynamic> j, T Function(Map<String, dynamic>) item); }
```
(`fromJson/toJson` = `factory X.fromJson(Map<String, dynamic> j)` and `Map<String, dynamic> toJson()`.)

`lib/core/providers.dart`
```dart
final localeProvider = StateProvider<Locale>((ref) => const Locale('ar'));
final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.light);
final displayCurrencyProvider = StateProvider<String>((ref) => 'USD');
final destinationProvider = StateProvider<Location?>((ref) => const Location(countryCode: 'IQ', city: 'Baghdad'));
```

`lib/core/theme/app_theme.dart` → `class AppColors { static const primary, primaryDark, accent, success, warning, danger, surface, background, textPrimary, textSecondary, border; }` and `class AppTheme { static ThemeData light(); static ThemeData dark(); }` and `class AppSpacing { static const double xs = 4, sm = 8, md = 12, lg = 16, xl = 24, xxl = 32; }` and `class AppRadius { static const double sm = 8, md = 14, lg = 20, xl = 28; }`.

`lib/core/widgets/widgets.dart` (barrel exporting all of these):
```dart
TrustBadge({super.key, required TrustBand band, int? score, bool compact = false})
MoneyText(Money money, {super.key, TextStyle? style})
MoneyText.range(MoneyRange range, {super.key, TextStyle? style})
AppCard({super.key, required Widget child, VoidCallback? onTap, EdgeInsetsGeometry? padding})
SectionHeader({super.key, required String title, String? actionLabel, VoidCallback? onAction})
EmptyState({super.key, required IconData icon, required String title, String? message, Widget? action})
ErrorState({super.key, required String message, VoidCallback? onRetry})
LoadingList({super.key, int itemCount = 6})
AppNetworkImage({super.key, required String? url, double? width, double? height, BoxFit fit = BoxFit.cover, BorderRadius? borderRadius})
PrimaryButton({super.key, required String label, VoidCallback? onPressed, IconData? icon, bool loading = false})
FilterChipBar({super.key, required List<String> labels, required int selectedIndex, required ValueChanged<int> onSelected})
CountryFlag({super.key, required String countryCode, double size = 18})   // emoji flag from ISO2
```

### Owned by features agents

- `lib/features/module_a.dart` exports `final FeatureModule featureModuleA` with branchRoutes for `'discover'` (root `/discover`, child `search`) and `'requests'` (root `/requests`, children `new`, `:id`), overlayRoutes `/listing/:id`, `/supplier/:id`.
- `lib/features/module_b.dart` exports `final FeatureModule featureModuleB` with branchRoutes for `'messages'` (root `/messages`, child `new` with query `supplier_id`, `listing_id`) and `'logistics'` (root `/logistics`, children `calculator` (query `listing_id` optional), `fx`, `carriers`, `tracking`, `tracking/:id`), overlayRoute `/chat/:id`.
- Cross-feature navigation uses paths only: features-a navigates to `/logistics/calculator?listing_id=<id>` and `/messages/new?supplier_id=<id>&listing_id=<id>`; features-b links back to `/listing/<id>`.
- When features-b needs a listing in mock mode (calculator prefill), it uses its own fixture; in live mode it calls `GET /v1/listings/{id}`.
- String keys are prefixed by feature folder (`discover.`, `listing.`, `requests.`, `logistics.`, `messages.`). Every key must exist in both `ar` and `en`.

## Launch prompt template (for reuse from the Code tab)

```
You are agent `<agent-id>` in the factory-finder repo. Read CLAUDE.md, docs/ARCHITECTURE.md and docs/AGENTS.md
(your row + any section that concerns you), then build your full scope autonomously. Write only inside the paths
you own. Do not run git. Run your tests until green. End with a short report.
```
