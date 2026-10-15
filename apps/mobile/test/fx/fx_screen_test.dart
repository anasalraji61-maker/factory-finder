import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/fx/data/fx_models.dart';
import 'package:factory_finder/features/fx/data/fx_repository.dart';
import 'package:factory_finder/features/fx/screens/fx_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Future<void> _pump(WidgetTester tester, List<Override> overrides) async {
  tester.view.physicalSize = const Size(360, 2400) * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: const MaterialApp(home: FxScreen()),
    ),
  );
  await settle(tester, frames: 4);
}

Future<void> _dispose(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  setUpWidgetTests();

  testWidgets('shows a rate row for every other currency', (tester) async {
    final repo = MockFxRepository(clock: () => DateTime.utc(2026, 10, 13, 12));
    await _pump(tester, [fxRepositoryProvider.overrideWithValue(repo)]);
    expect(find.text('Exchange rates'), findsOneWidget);
    expect(find.text('1 USD = EUR'), findsOneWidget);
    expect(find.text('1 USD = IQD'), findsOneWidget);
    expect(find.text('1 USD = USD'), findsNothing);
    await _dispose(tester);
  });

  testWidgets('selecting a base currency reloads the rates', (tester) async {
    final repo = MockFxRepository(clock: () => DateTime.utc(2026, 10, 13, 12));
    await _pump(tester, [fxRepositoryProvider.overrideWithValue(repo)]);
    final bar = tester.widget<FilterChipBar>(find.byType(FilterChipBar));
    bar.onSelected(kFxCurrencies.indexOf('EUR'));
    await settle(tester, frames: 4);
    expect(find.text('1 EUR = USD'), findsOneWidget);
    expect(find.text('1 EUR = EUR'), findsNothing);
    await _dispose(tester);
  });

  testWidgets('empty rates show the empty state', (tester) async {
    await _pump(tester, [
      fxRatesProvider.overrideWith(
          (ref, base) async => FxRates(base: base, rates: const {})),
    ]);
    expect(find.text('No rates available'), findsOneWidget);
    await _dispose(tester);
  });

  testWidgets('failure shows an error state with retry', (tester) async {
    await _pump(tester, [
      fxRatesProvider.overrideWith((ref, base) async => throw StateError('boom')),
    ]);
    expect(find.byType(ErrorState), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    await _dispose(tester);
  });
}
