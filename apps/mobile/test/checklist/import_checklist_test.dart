import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/checklist/checklist_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

void main() {
  setUpWidgetTests();

  test('logic: storage key, codec and insurance flag', () {
    expect(checklistStorageKey('iq', 'fob'), 'checklist.v1.IQ.FOB');
    expect(decodeChecked(encodeChecked({'b', 'a'})), {'a', 'b'});
    expect(decodeChecked(null), isEmpty);
    expect(checklistDocsFor('FOB').firstWhere((d) => d.id == 'insurance').insuranceIncluded, isFalse);
    expect(checklistDocsFor('CIF').firstWhere((d) => d.id == 'insurance').insuranceIncluded, isTrue);
  });

  testWidgets('renders Arabic checklist with disclaimer and zero progress', (tester) async {
    await pumpApp(tester, location: '/import-checklist', logicalSize: const Size(540, 2400));
    expect(find.text('قائمة وثائق الاستيراد'), findsOneWidget);
    expect(find.text('الفاتورة التجارية'), findsOneWidget);
    expect(find.text('قائمة التعبئة'), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('checklist-disclaimer')), findsOneWidget);
    expect(find.textContaining('المخلّص الجمركي'), findsOneWidget);
    final bar = tester.widget<LinearProgressIndicator>(
        find.byKey(const ValueKey<String>('checklist-progress-bar')));
    expect(bar.value, 0);
    await disposeApp(tester);
  });

  testWidgets('toggle updates progress and persists to the store', (tester) async {
    final store = MemoryStore();
    await pumpApp(
      tester,
      location: '/import-checklist',
      logicalSize: const Size(540, 2400),
      overrides: [keyValueStoreProvider.overrideWithValue(store)],
    );
    await tester.tap(find.byKey(const ValueKey<String>('checklist-item-invoice')));
    await settle(tester, frames: 3);
    expect(store.data['checklist.v1.IQ.FOB'], 'invoice');
    final bar = tester.widget<LinearProgressIndicator>(
        find.byKey(const ValueKey<String>('checklist-progress-bar')));
    expect(bar.value, closeTo(1 / 7, 1e-9));
    await disposeApp(tester);
  });

  testWidgets('saved state is restored on open', (tester) async {
    final store = MemoryStore({'checklist.v1.IQ.FOB': 'invoice,packing'});
    await pumpApp(
      tester,
      location: '/import-checklist',
      logicalSize: const Size(540, 2400),
      overrides: [keyValueStoreProvider.overrideWithValue(store)],
    );
    final tile = tester.widget<CheckboxListTile>(
        find.byKey(const ValueKey<String>('checklist-item-packing')));
    expect(tile.value, isTrue);
    final bar = tester.widget<LinearProgressIndicator>(
        find.byKey(const ValueKey<String>('checklist-progress-bar')));
    expect(bar.value, closeTo(2 / 7, 1e-9));
    await disposeApp(tester);
  });

  testWidgets('switching incoterm loads that incoterm\'s own state', (tester) async {
    final store = MemoryStore({'checklist.v1.IQ.CIF': 'origin'});
    await pumpApp(
      tester,
      location: '/import-checklist',
      logicalSize: const Size(540, 2400),
      overrides: [keyValueStoreProvider.overrideWithValue(store)],
    );
    await tester.tap(find.byKey(const ValueKey<String>('checklist-incoterm-CIF')));
    await settle(tester, frames: 3);
    final tile = tester.widget<CheckboxListTile>(
        find.byKey(const ValueKey<String>('checklist-item-origin')));
    expect(tile.value, isTrue);
    await disposeApp(tester);
  });
}
