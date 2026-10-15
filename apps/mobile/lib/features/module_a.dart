import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/auth/auth_screens.dart';
import 'package:factory_finder/features/auth/auth_strings.dart';
import 'package:factory_finder/features/onboarding/onboarding_screen.dart';
import 'package:factory_finder/features/onboarding/onboarding_strings.dart';
import 'package:factory_finder/features/payments/payments_strings.dart';
import 'package:factory_finder/features/payments/screens/invoice_screen.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/requests_strings.dart';
import 'package:factory_finder/features/requests/screens/create_request_screen.dart';
import 'package:factory_finder/features/requests/screens/request_detail_screen.dart';
import 'package:factory_finder/features/requests/screens/requests_screen.dart';
import 'package:factory_finder/features/discover/compare_strings.dart';
import 'package:factory_finder/features/discover/discover_strings.dart';
import 'package:factory_finder/features/discover/report_strings.dart';
import 'package:factory_finder/features/discover/screens/compare_screen.dart';
import 'package:factory_finder/features/discover/screens/discover_screen.dart';
import 'package:factory_finder/features/discover/screens/listing_detail_screen.dart';
import 'package:factory_finder/features/discover/screens/search_screen.dart';
import 'package:factory_finder/features/discover/screens/supplier_screen.dart';
import 'package:factory_finder/features/reco/reco_strings.dart';
import 'package:factory_finder/features/reviews/reviews_strings.dart';
import 'package:factory_finder/features/reviews/screens/reviews_list_screen.dart';
import 'package:factory_finder/features/supplier_claim/supplier_claim_screen.dart';
import 'package:factory_finder/features/supplier_claim/supplier_claim_strings.dart';
import 'package:factory_finder/features/watchlist/screens/alerts_screen.dart';
import 'package:factory_finder/features/watchlist/screens/watchlist_screen.dart';
import 'package:factory_finder/features/watchlist/watchlist_strings.dart';
import 'package:factory_finder/features/deals/deals_strings.dart';
import 'package:factory_finder/features/deals/screens/deal_detail_screen.dart';
import 'package:factory_finder/features/deals/screens/deals_list_screen.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_screen.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_strings.dart';
import 'package:factory_finder/features/trust/trust_strings.dart';
import 'package:factory_finder/features/trust/verification_screen.dart';
import 'package:factory_finder/features/trust/verification_strings.dart';
import 'package:go_router/go_router.dart';

/// Discover tab, listing detail, supplier page, Requests & Offers, auth screens.
final FeatureModule featureModuleA = FeatureModule(
  branchRoutes: {
    'discover': [
      GoRoute(
        path: '/discover',
        builder: (context, state) => const DiscoverScreen(),
        routes: [
          GoRoute(
            path: 'search',
            builder: (context, state) => SearchScreen(
              initialQuery: state.uri.queryParameters['q'] ?? '',
            ),
          ),
        ],
      ),
    ],
    'requests': [
      GoRoute(
        path: '/requests',
        builder: (context, state) => const RequestsScreen(),
        routes: [
          GoRoute(
            path: 'new',
            builder: (context, state) {
              final sid = state.uri.queryParameters['supplier'];
              final name = state.uri.queryParameters['supplier_name'];
              return CreateRequestScreen(
                initialInvites: (sid == null || !isValidInviteId(sid))
                    ? const <InvitedSupplier>[]
                    : <InvitedSupplier>[
                        InvitedSupplier(
                          id: sid,
                          name: (name == null || name.isEmpty) ? sid : name,
                        ),
                      ],
              );
            },
          ),
          GoRoute(
            path: ':id',
            builder: (context, state) =>
                RequestDetailScreen(requestId: state.pathParameters['id']!),
          ),
        ],
      ),
    ],
  },
  overlayRoutes: [
    GoRoute(path: '/onboarding', builder: (context, state) => const OnboardingScreen()),
    GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
    GoRoute(path: '/register', builder: (context, state) => const RegisterScreen()),
    GoRoute(
      path: '/supplier-claim',
      builder: (context, state) => const SupplierClaimScreen(),
    ),
    GoRoute(
      path: '/verification',
      builder: (context, state) => const VerificationScreen(),
    ),
    GoRoute(
      path: '/listing/:id',
      builder: (context, state) =>
          ListingDetailScreen(listingId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/invoice/:id',
      builder: (context, state) =>
          InvoiceScreen(invoiceId: state.pathParameters['id']!),
    ),
    GoRoute(path: '/compare', builder: (context, state) => const CompareScreen()),
    GoRoute(path: '/watchlist', builder: (context, state) => const WatchlistScreen()),
    GoRoute(path: '/deals', builder: (context, state) => const DealsListScreen()),
    GoRoute(
      path: '/deals/:id',
      builder: (context, state) =>
          DealDetailScreen(dealId: state.pathParameters['id']!),
    ),
    GoRoute(path: '/alerts', builder: (context, state) => const AlertsScreen()),
    GoRoute(
      path: '/notification-prefs',
      builder: (context, state) => const NotifyPrefsScreen(),
    ),
    GoRoute(
      path: '/supplier-reviews/:id',
      builder: (context, state) =>
          ReviewsListScreen(supplierRef: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/supplier/:id',
      builder: (context, state) =>
          SupplierScreen(supplierId: state.pathParameters['id']!),
    ),
  ],
  strings: mergeStringTables([discoverStrings, reportStrings, compareStrings, requestsStrings, authStrings, supplierClaimStrings, watchlistStrings, onboardingStrings, trustStrings, verificationStrings, notifyPrefsStrings, paymentsStrings, reviewsStrings, dealsStrings, recoStrings]),
);
