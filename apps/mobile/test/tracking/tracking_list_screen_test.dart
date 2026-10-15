import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/tracking_list_screen.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Future<void> _pump(WidgetTester tester, List<Override> overrides) async {
  // Narrow phone width (360) to catch overflow in the shipment cards.
  tester.view.physicalSize = const Size(360, 2400) * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: const MaterialApp(home: TrackingListScreen()),
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

  testWidgets('lists mock shipments with the add button', (tester) async {
    final repo = MockTrackingRepository(clock: () => DateTime(2026, 10, 13, 12));
    final list = await repo.shipments();
    await _pump(tester, [trackingRepositoryProvider.overrideWithValue(repo)]);

    expect(find.text('Shipment tracking'), findsOneWidget);
    expect(find.text('Add shipment'), findsOneWidget);
    expect(find.byType(StatusChip), findsWidgets);
    expect(find.text(list.first.reference), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsWidgets);
    await _dispose(tester);
  });

  testWidgets('empty list shows the empty state', (tester) async {
    await _pump(tester, [shipmentsProvider.overrideWith((ref) async => [])]);
    expect(find.text('No shipments yet'), findsOneWidget);
    expect(find.byType(StatusChip), findsNothing);
    await _dispose(tester);
  });

  testWidgets('failure shows an error state with retry', (tester) async {
    var calls = 0;
    await _pump(tester, [
      shipmentsProvider.overrideWith((ref) async {
        calls++;
        throw StateError('boom');
      }),
    ]);
    expect(find.byType(ErrorState), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    final before = calls;
    await tester.tap(find.text('Retry'));
    await settle(tester, frames: 3);
    expect(calls, greaterThan(before));
    await _dispose(tester);
  });
}
