import 'package:factory_finder/features/carriers/data/carrier_models.dart';
import 'package:factory_finder/features/carriers/data/carriers_repository.dart';
import 'package:factory_finder/features/carriers/screens/carriers_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

const _carriers = [
  Carrier(
    id: 'c1',
    name: 'Alpha Lines',
    modes: ['sea_fcl_20'],
    originRegions: ['CN'],
    destinationRegions: ['IQ'],
    rating: 4.5,
  ),
  Carrier(id: 'c2', name: 'Beta Air', kind: 'airline', modes: ['air'], rating: 3.0),
];

Future<void> _pump(WidgetTester tester, List<Carrier> data) async {
  tester.view.physicalSize = const Size(360, 2400) * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [carriersProvider.overrideWith((ref) async => data)],
      child: const MaterialApp(home: CarriersScreen()),
    ),
  );
  await settle(tester, frames: 3);
}

Future<void> _dispose(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  setUpWidgetTests();

  testWidgets('shows all carriers by default', (tester) async {
    await _pump(tester, _carriers);
    expect(find.text('Carriers'), findsOneWidget);
    expect(find.text('Alpha Lines'), findsOneWidget);
    expect(find.text('Beta Air'), findsOneWidget);
    expect(find.byType(CarrierCard), findsNWidgets(2));
    await _dispose(tester);
  });

  testWidgets('mode filter narrows the list', (tester) async {
    await _pump(tester, _carriers);
    final container = ProviderScope.containerOf(tester.element(find.byType(CarriersScreen)));
    container.read(carrierModeGroupProvider.notifier).state = 'air';
    await settle(tester, frames: 3);
    expect(find.text('Beta Air'), findsOneWidget);
    expect(find.text('Alpha Lines'), findsNothing);
    // A group with no carriers shows the empty state.
    container.read(carrierModeGroupProvider.notifier).state = 'rail';
    await settle(tester, frames: 3);
    expect(find.byType(CarrierCard), findsNothing);
    expect(find.text('No carriers found'), findsOneWidget);
    await _dispose(tester);
  });

  testWidgets('empty data shows the empty state', (tester) async {
    await _pump(tester, const []);
    expect(find.text('No carriers found'), findsOneWidget);
    await _dispose(tester);
  });
}
