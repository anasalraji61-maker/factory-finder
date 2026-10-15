import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/data/mock_freight_repository.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

ValueKey<String> k(String id) => ValueKey<String>(id);

Future<void> _pump(WidgetTester tester, String location, List<Override> overrides) async {
  tester.view.physicalSize = const Size(1080, 21000);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = createAppRouter();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        ...overrides,
      ],
      child: FactoryFinderApp(router: router),
    ),
  );
  await settle(tester);
  router.go(location);
  await settle(tester);
}

Future<void> _expandAll(WidgetTester tester) async {
  // Only tiles on the visible route (the calculator route may still be in
  // the stack). Expand each once; expanded tiles are tracked by index.
  final n = find.byType(ExpansionTile).hitTestable().evaluate().length;
  for (var i = 0; i < n; i++) {
    final tiles = find.byType(ExpansionTile).hitTestable();
    if (tiles.evaluate().length <= i) break;
    await tester.tap(tiles.at(i), warnIfMissed: false);
    await settle(tester, frames: 4);
  }
}

void main() {
  setUpWidgetTests();

  testWidgets('awarded quote -> calculator prefilled -> quoted pill on result', (tester) async {
    // Real clock: the quote generator checks override validity against now.
    final repo = MockFreightRepository(clock: () => DateTime.now().toUtc());
    await _pump(tester, '/logistics/freight/requests/fr_102', [
      freightRepositoryProvider.overrideWithValue(repo),
    ]);

    await tester.ensureVisible(find.byKey(k('freight_use_landed_fq_102_1')));
    await tester.tap(find.byKey(k('freight_use_landed_fq_102_1')));
    await settle(tester);

    expect(find.byKey(k('calc_override_banner')), findsOneWidget);

    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '10');
    await tester.enterText(fields.at(1), '100');
    await tester.enterText(fields.at(2), '120');
    await tester.enterText(fields.at(3), '0.5');
    await tester.pump();
    await tester.ensureVisible(find.text('احسب الكلفة'));
    await tester.tap(find.text('احسب الكلفة'));
    await settle(tester, frames: 30);

    expect(find.text('نتائج التسعير'), findsOneWidget);
    await _expandAll(tester);
    expect(find.byKey(k('quoted_pill')), findsOneWidget);
    expect(find.byKey(k('quoted_note')), findsOneWidget);
    expect(find.text('عرض شركة الشحن'), findsOneWidget);
    // Other lines keep the estimate label.
    expect(find.text('تقدير'), findsWidgets);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('no landed-cost button on a request that is still open', (tester) async {
    final repo = MockFreightRepository(clock: () => DateTime.utc(2026, 10, 15, 12));
    await _pump(tester, '/logistics/freight/requests/fr_100', [
      freightRepositoryProvider.overrideWithValue(repo),
    ]);
    expect(find.byKey(k('freight_use_landed_fq_100_1')), findsNothing);
    await disposeApp(tester);
  });

  testWidgets('results screen shows pill only for quoted lines', (tester) async {
    final request = QuoteRequest(
      goodsValue: 5000,
      weightKg: 800,
      volumeM3: 3,
      origin: const Location(countryCode: 'CN', city: 'Guangzhou'),
      destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
      freightOverride: FreightOverride(
        amount: '900.00',
        currency: 'USD',
        quoteId: 'fq_x',
        validUntil: DateTime.utc(2099, 1, 1),
        modeFamily: 'sea',
      ),
    );
    final quote = MockQuoteGenerator.generate(request, lang: 'ar');
    await _pump(tester, '/logistics/results', [
      lastQuoteProvider.overrideWith((ref) => quote),
      lastQuoteRequestProvider.overrideWith((ref) => request),
    ]);
    await _expandAll(tester);
    expect(find.byKey(k('quoted_pill')), findsOneWidget);
    expect(find.byKey(k('quoted_note')), findsOneWidget);
    expect(find.textContaining('صالح حتى'), findsOneWidget);
    await disposeApp(tester);
  });
}
