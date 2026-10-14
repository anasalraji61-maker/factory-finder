import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/assistant/assistant_strings.dart';
import 'package:factory_finder/features/assistant/screens/assistant_screen.dart';
import 'package:factory_finder/features/my_products/my_products_strings.dart';
import 'package:factory_finder/features/my_products/screens/my_products_screen.dart';
import 'package:factory_finder/features/my_products/screens/product_editor_screen.dart';
import 'package:factory_finder/features/settings/settings_screen.dart';
import 'package:factory_finder/features/settings/settings_strings.dart';
import 'package:go_router/go_router.dart';

/// Supplier "My products" (list + editor).
final FeatureModule featureModuleC = FeatureModule(
  overlayRoutes: [
    GoRoute(
      path: '/assistant',
      builder: (context, state) => const AssistantScreen(),
    ),
    GoRoute(
      path: '/settings',
      builder: (context, state) => const SettingsScreen(),
    ),
    GoRoute(
      path: '/my-products',
      builder: (context, state) => const MyProductsScreen(),
    ),
    GoRoute(
      path: '/my-products/new',
      builder: (context, state) => const ProductEditorScreen(),
    ),
    GoRoute(
      path: '/my-products/:id',
      builder: (context, state) =>
          ProductEditorScreen(listingId: state.pathParameters['id']),
    ),
  ],
  strings: mergeStringTables([myProductsStrings, assistantStrings, settingsStrings]),
);
