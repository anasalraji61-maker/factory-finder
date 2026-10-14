import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  testWidgets('onboarding: three pages then lands on the app shell', (tester) async {
    await pumpApp(tester, location: '/onboarding');
    expect(find.text('مرحباً بك في مُوَرِّد'), findsOneWidget);

    await tester.tap(find.text('التالي'));
    await settle(tester);
    expect(find.text('خصّص تجربتك'), findsOneWidget);

    await tester.tap(find.text('التالي'));
    await settle(tester);
    expect(find.text('كيف ستستخدم التطبيق؟'), findsOneWidget);

    await tester.tap(find.text('ابدأ'));
    await settle(tester, frames: 12);
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('onboarding: skip goes straight to the app shell', (tester) async {
    await pumpApp(tester, location: '/onboarding');
    await tester.tap(find.text('تخطّي'));
    await settle(tester, frames: 12);
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('calculator: HS search suggests a code and shows the duty estimate', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator');
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(4), 'earbuds');
    await tester.pump(const Duration(milliseconds: 350));
    await settle(tester, frames: 4);

    final tile = find.byKey(const ValueKey('hs-851830'));
    expect(tile, findsOneWidget);
    await tester.ensureVisible(tile);
    await tester.tap(tile);
    await settle(tester, frames: 3);

    expect(find.byKey(const ValueKey('hs-851830')), findsNothing);
    expect(find.textContaining('≈ 5%'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('search: sort dropdown and facet counts on filter chips', (tester) async {
    await pumpApp(tester, location: '/discover/search');
    await settle(tester, frames: 10);

    await tester.tap(find.byKey(const ValueKey('search-sort')));
    await settle(tester, frames: 3);
    await tester.tap(find.text('أقل كمية طلب').last);
    await settle(tester, frames: 8);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byIcon(Icons.tune));
    await settle(tester, frames: 4);
    expect(find.textContaining('منتجات ('), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
