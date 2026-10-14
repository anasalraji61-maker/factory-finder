import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  testWidgets('compare: add two listings from search, open the table', (tester) async {
    await pumpApp(tester, location: '/discover/search');

    await tester.tap(find.byIcon(Icons.compare_arrows).first);
    await settle(tester, frames: 2);
    expect(find.text('المقارنة: 1 من 3'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.compare_arrows).first);
    await settle(tester, frames: 2);
    expect(find.text('المقارنة: 2 من 3'), findsOneWidget);

    await tester.tap(find.text('قارن'));
    await settle(tester, frames: 20);
    expect(find.text('مقارنة المنتجات'), findsOneWidget);
    expect(find.text('نطاق السعر'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('saved search: empty warns, keywords save', (tester) async {
    await pumpApp(tester, location: '/discover/search');
    final messenger =
        ScaffoldMessenger.of(tester.element(find.byType(Scaffold).first));

    await tester.tap(find.byIcon(Icons.bookmark_add_outlined));
    await settle(tester, frames: 3);
    expect(find.text('أدخل كلمات بحث أو فلاتر أولاً'), findsOneWidget);
    messenger.clearSnackBars();
    await settle(tester, frames: 6);

    await tester.enterText(find.byType(TextField).first, 'led');
    await tester.tap(find.byIcon(Icons.bookmark_add_outlined));
    await settle(tester, frames: 3);
    expect(find.text('تم حفظ البحث وسنخبرك بالنتائج الجديدة'), findsOneWidget);
    messenger.clearSnackBars();
    await settle(tester, frames: 6);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
