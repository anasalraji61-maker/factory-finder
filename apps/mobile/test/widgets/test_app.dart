import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

/// Shared setup for widget tests. Runs in mock mode (FF_MOCK defaults to true),
/// with no network: runtime font fetching and network images are disabled.
void setUpWidgetTests() {
  setUpAll(() {
    registerFeatureStrings();
    GoogleFonts.config.allowRuntimeFetching = false;
    debugDisableNetworkImages = true;
  });
  tearDownAll(() {
    debugDisableNetworkImages = false;
  });
}

/// Pumps the real app with a fresh router (so tests do not share navigation
/// state) on a large phone-like surface. Returns the router.
Future<GoRouter> pumpApp(WidgetTester tester, {String? location}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final router = createAppRouter();
  await tester.pumpWidget(
    ProviderScope(child: FactoryFinderApp(router: router)),
  );
  await settle(tester);
  if (location != null) {
    router.go(location);
    await settle(tester);
  }
  return router;
}

/// Unmounts the app so providers, polling timers and snackbars are disposed
/// before the framework checks for pending timers.
Future<void> disposeApp(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
}

/// Bounded replacement for pumpAndSettle (shimmers and spinners never settle).
Future<void> settle(WidgetTester tester, {int frames = 8}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Finder navLabel(String text) => find.descendant(
      of: find.byType(NavigationBar),
      matching: find.text(text),
    );
