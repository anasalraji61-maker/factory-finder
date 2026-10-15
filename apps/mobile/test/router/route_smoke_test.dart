import 'package:factory_finder/core/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

/// Every static route in `app_router.dart` / the feature modules, plus the
/// parameterised ones that mock data can serve. Keep in sync with the router.
const List<String> _routes = <String>[
  // Shell tabs and their children.
  '/discover',
  '/discover/search',
  '/requests',
  '/requests/new',
  '/messages',
  '/messages/new',
  '/logistics',
  '/logistics/calculator',
  '/logistics/results',
  '/logistics/fx',
  '/logistics/carriers',
  '/logistics/freight',
  '/logistics/freight/new',
  '/logistics/freight/forwarder/apply',
  '/logistics/tracking',
  '/profile',
  // Overlay routes.
  '/onboarding',
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
  '/settings',
  '/settings/change-password',
  '/settings/privacy',
  '/settings/privacy/blocked',
  '/supplier-claim',
  '/verification',
  '/compare',
  '/watchlist',
  '/deals',
  '/alerts',
  '/notification-prefs',
  '/assistant',
  '/feed',
  '/feed/new',
  '/my-products',
  '/my-products/analytics',
  '/my-products/import',
  '/my-products/new',
  // Parameterised routes with ids known to the mock data.
  '/listing/lst_001',
  '/supplier/sup_cn_004',
  '/chat/cnv_001',
];

void main() {
  setUpWidgetTests();

  for (final lang in const ['ar', 'en']) {
    final expectedDir = lang == 'ar' ? TextDirection.rtl : TextDirection.ltr;
    for (final route in _routes) {
      testWidgets('route $route renders without errors ($lang)', (tester) async {
        await pumpApp(
          tester,
          location: route,
          logicalSize: const Size(540, 2400),
          overrides: [
            localeProvider.overrideWith((ref) => Locale(lang)),
          ],
        );

        expect(tester.takeException(), isNull, reason: route);
        expect(find.byType(Scaffold), findsWidgets, reason: route);
        expect(
          Directionality.of(tester.element(find.byType(Scaffold).first)),
          expectedDir,
          reason: route,
        );

        await disposeApp(tester);
        expect(tester.takeException(), isNull, reason: '$route (dispose)');
      });
    }
  }
}
