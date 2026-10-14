import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  testWidgets('app boots in Arabic RTL and every bottom tab opens', (tester) async {
    await pumpApp(tester);

    // Five tabs, Arabic labels.
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.descendant(of: find.byType(NavigationBar), matching: find.byType(NavigationDestination)),
        findsNWidgets(5));
    for (final label in ['استكشف', 'الطلبات', 'الرسائل', 'الشحن', 'حسابي']) {
      expect(navLabel(label), findsOneWidget, reason: label);
    }
    expect(
      Directionality.of(tester.element(find.byType(NavigationBar))),
      TextDirection.rtl,
    );

    // Discover is the initial tab.
    expect(find.text('الأكثر رواجاً'), findsWidgets);

    await tester.tap(navLabel('الطلبات'));
    await settle(tester);
    expect(find.text('الطلبات والعروض'), findsOneWidget);

    await tester.tap(navLabel('الرسائل'));
    await settle(tester);
    expect(find.text('الرسائل'), findsWidgets);

    await tester.tap(navLabel('الشحن'));
    await settle(tester);
    expect(find.text('الشحن والكلفة'), findsOneWidget);

    await tester.tap(navLabel('حسابي'));
    await settle(tester);
    expect(find.text('زائر'), findsOneWidget);

    await tester.tap(navLabel('استكشف'));
    await settle(tester);
    expect(find.text('الأكثر رواجاً'), findsWidgets);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
