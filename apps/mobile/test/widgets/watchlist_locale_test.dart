import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  testWidgets('listing detail: watch toggles on and off', (tester) async {
    await pumpApp(tester, location: '/listing/lst_001');
    await settle(tester, frames: 6); // mock listing delay

    expect(find.byTooltip('متابعة المنتج'), findsOneWidget);

    // Add: opens the threshold sheet, confirm with empty thresholds.
    await tester.tap(find.byTooltip('متابعة المنتج'));
    await settle(tester, frames: 4);
    expect(find.text('ابدأ المتابعة'), findsOneWidget);
    await tester.tap(find.text('ابدأ المتابعة'));
    await settle(tester, frames: 6);
    expect(find.text('تمت إضافة المنتج إلى قائمة المتابعة'), findsOneWidget);
    expect(find.byTooltip('تتم متابعته'), findsOneWidget);

    // Let the 'added' snackbar expire so the queued 'removed' one can show.
    await tester.pump(const Duration(seconds: 5));
    await settle(tester, frames: 4);

    // Remove: no sheet, straight to the removed snackbar.
    await tester.tap(find.byTooltip('تتم متابعته'));
    await settle(tester, frames: 8);
    expect(find.text('تمت إزالة المنتج من قائمة المتابعة'), findsOneWidget);
    expect(find.byTooltip('متابعة المنتج'), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('profile: switching language ar -> en flips labels and direction', (tester) async {
    await pumpApp(tester, location: '/profile');
    expect(navLabel('حسابي'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.byType(NavigationBar))),
      TextDirection.rtl,
    );

    await tester.tap(find.text('English'));
    await settle(tester, frames: 4);

    final container =
        ProviderScope.containerOf(tester.element(find.byType(FactoryFinderApp)));
    expect(container.read(localeProvider).languageCode, 'en');
    expect(navLabel('Profile'), findsOneWidget);
    expect(navLabel('Discover'), findsOneWidget);
    expect(navLabel('حسابي'), findsNothing);
    expect(find.text('Guest'), findsOneWidget);
    expect(
      Directionality.of(tester.element(find.byType(NavigationBar))),
      TextDirection.ltr,
    );

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
