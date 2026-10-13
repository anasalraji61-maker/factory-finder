import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/features/logistics/logistics_strings.dart';
import 'package:factory_finder/features/logistics/screens/calculator_screen.dart';
import 'package:factory_finder/features/logistics/screens/logistics_screen.dart';
import 'package:factory_finder/features/logistics/screens/results_screen.dart';
import 'package:factory_finder/features/messages/messages_strings.dart';
import 'package:factory_finder/features/messages/screens/chat_screen.dart';
import 'package:factory_finder/features/messages/screens/conversations_screen.dart';
import 'package:factory_finder/features/messages/screens/new_conversation_screen.dart';
import 'package:factory_finder/features/tracking/screens/tracking_detail_screen.dart';
import 'package:factory_finder/features/tracking/screens/tracking_list_screen.dart';
import 'package:factory_finder/features/tracking/tracking_strings.dart';
import 'package:go_router/go_router.dart';

/// Logistics tab (calculator, results, tracking) and the Messages tab.
final FeatureModule featureModuleB = FeatureModule(
  branchRoutes: {
    'messages': [
      GoRoute(
        path: '/messages',
        builder: (context, state) => const ConversationsScreen(),
        routes: [
          GoRoute(
            path: 'new',
            builder: (context, state) => NewConversationScreen(
              supplierId: state.uri.queryParameters['supplier_id'],
              listingId: state.uri.queryParameters['listing_id'],
            ),
          ),
        ],
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
          GoRoute(
            path: 'tracking',
            builder: (context, state) => const TrackingListScreen(),
            routes: [
              GoRoute(
                path: ':id',
                builder: (context, state) => TrackingDetailScreen(
                  shipmentId: state.pathParameters['id'] ?? '',
                ),
              ),
            ],
          ),
        ],
      ),
    ],
  },
  overlayRoutes: [
    GoRoute(
      path: '/chat/:id',
      builder: (context, state) =>
          ChatScreen(conversationId: state.pathParameters['id'] ?? ''),
    ),
  ],
  strings: _mergedStrings,
);

final Map<String, Map<String, String>> _mergedStrings = {
  for (final lang in const ['ar', 'en'])
    lang: {
      ...?logisticsStrings[lang],
      ...?messagesStrings[lang],
      ...?trackingStrings[lang],
    },
};
