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
  '/requests/req_001',
  '/requests/req_005',
  '/feed/post/post_001',
  '/feed/supplier/sup_cn_001',
  '/supplier-reviews/sup_cn_004',
  '/logistics/tracking/shp_001',
  '/logistics/tracking/shp_005',
  '/logistics/freight/requests/fr_100',
  '/logistics/freight/forwarder/requests/fr_200',
  // Not seeded in mock data (deals/invoices appear only after accepting an
  // offer; my-products starts empty): exercises the not-found/error states.
  '/deals/deal_101',
  '/invoice/inv_mock_1',
  '/my-products/lst_mock_my_001',
];

/// Main tab roots, re-run on a small 360 dp phone to catch overflow.
const List<String> _tabRoutes = <String>[
  '/discover',
  '/requests',
  '/messages',
  '/logistics',
  '/profile',
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

  // Small phone: 360 x 800 dp (1080 x 2400 px @ 3.0). Overflow errors are
  // reported through tester.takeException().
  for (final lang in const ['ar', 'en']) {
    for (final route in _tabRoutes) {
      testWidgets('route $route fits a 360dp phone ($lang)', (tester) async {
        await pumpApp(
          tester,
          location: route,
          logicalSize: const Size(360, 800),
          devicePixelRatio: 3.0,
          overrides: [
            localeProvider.overrideWith((ref) => Locale(lang)),
          ],
        );

        expect(tester.takeException(), isNull, reason: '$route @360');
        expect(find.byType(Scaffold), findsWidgets, reason: route);

        await disposeApp(tester);
        expect(tester.takeException(), isNull, reason: '$route @360 (dispose)');
      });
    }
  }
}
