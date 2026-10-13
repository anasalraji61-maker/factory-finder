import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/logistics/logistics_strings.dart';
import 'package:factory_finder/features/logistics/screens/calculator_screen.dart';
import 'package:factory_finder/features/logistics/screens/logistics_screen.dart';
import 'package:factory_finder/features/logistics/screens/results_screen.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Logistics tab (calculator + results) and the Messages placeholder.
final FeatureModule featureModuleB = FeatureModule(
  branchRoutes: {
    'messages': [
      GoRoute(
        path: '/messages',
        builder: (context, state) => const ComingSoonScreen(
          titleKey: 'nav.messages',
          icon: Icons.chat_bubble_outline,
        ),
      ),
    ],
    'logistics': [
      GoRoute(
        path: '/logistics',
        builder: (context, state) => const LogisticsScreen(),
        routes: [
          GoRoute(
            path: 'calculator',
            builder: (context, state) => CalculatorScreen(
              listingId: state.uri.queryParameters['listing_id'],
            ),
          ),
          GoRoute(
            path: 'results',
            builder: (context, state) => const ResultsScreen(),
          ),
        ],
      ),
    ],
  },
  strings: logisticsStrings,
);
