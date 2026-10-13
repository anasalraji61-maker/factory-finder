import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/discover_strings.dart';
import 'package:factory_finder/features/discover/screens/discover_screen.dart';
import 'package:factory_finder/features/discover/screens/listing_detail_screen.dart';
import 'package:factory_finder/features/discover/screens/search_screen.dart';
import 'package:factory_finder/features/discover/screens/supplier_screen.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Discover tab, listing detail, supplier page, and the Requests placeholder.
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
        builder: (context, state) => const ComingSoonScreen(
          titleKey: 'nav.requests',
          icon: Icons.request_quote_outlined,
        ),
      ),
    ],
  },
  overlayRoutes: [
    GoRoute(
      path: '/listing/:id',
      builder: (context, state) =>
          ListingDetailScreen(listingId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: '/supplier/:id',
      builder: (context, state) =>
          SupplierScreen(supplierId: state.pathParameters['id']!),
    ),
  ],
  strings: discoverStrings,
);
