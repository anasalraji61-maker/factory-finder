import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  testWidgets('calculator: invalid input warns, valid input shows a quote', (tester) async {
    await pumpApp(tester, location: '/logistics/calculator');
    expect(find.text('حاسبة الكلفة'), findsOneWidget);

    // Empty form -> validation snackbar, no navigation.
    await tester.tap(find.text('احسب الكلفة'));
    await settle(tester, frames: 3);
    expect(find.text('أدخل القيمة والوزن بشكل صحيح'), findsOneWidget);
    expect(find.text('نتائج التسعير'), findsNothing);

    // Let the validation snackbar expire so it cannot cover the button.
    await tester.pump(const Duration(seconds: 5));
    await settle(tester, frames: 4);
    expect(find.text('أدخل القيمة والوزن بشكل صحيح'), findsNothing);

    // Fields in "by unit" mode: unit price, quantity, weight, volume, HS code.
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '10');
    await tester.enterText(fields.at(1), '100');
    await tester.enterText(fields.at(2), '120');
    await tester.enterText(fields.at(3), '0.5');
    await tester.pump();

    await tester.ensureVisible(find.text('احسب الكلفة'));
    await tester.tap(find.text('احسب الكلفة'));
    await settle(tester, frames: 30);
    // ignore: avoid_print
    print('VISIBLE: ' + find.byType(Text).evaluate().map((e) => (e.widget as Text).data ?? '').where((t) => t.isNotEmpty).take(25).join(' | '));

    expect(find.text('نتائج التسعير'), findsOneWidget);
    expect(find.text('لا توجد تسعيرة بعد'), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('FX converter: default and edited amount convert USD to IQD', (tester) async {
    await pumpApp(tester, location: '/logistics/fx');
    expect(find.text('محوّل العملات'), findsOneWidget);

    // Default 100 USD at the mock rate of 1310.
    expect(find.text('131,000 IQD'), findsOneWidget);

    await tester.enterText(find.byType(TextField).first, '250');
    await settle(tester, frames: 3);
    expect(find.text('327,500 IQD'), findsOneWidget);
    expect(find.text('131,000 IQD'), findsNothing);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
