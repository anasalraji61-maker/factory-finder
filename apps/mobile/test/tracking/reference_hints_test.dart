import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/add_shipment_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

void main() {
  setUpWidgetTests();

  group('ReferenceCheck.fromJson', () {
    test('full payload', () {
      final c = ReferenceCheck.fromJson({
        'reference': 'MSKU123456S',
        'valid': false,
        'normalized': 'MSKU123456S',
        'reason': 'format',
        'suggestions': ['MSKU1234565', 'A', 'B', 'C'],
        'carrier_suggestion': {
          'code': 'MAERSK',
          'name': 'Maersk',
          'name_ar': 'ميرسك',
          'confidence': 'high',
          'indicative': true,
        },
      });
      expect(c.valid, isFalse);
      expect(c.suggestions, ['MSKU1234565', 'A', 'B']);
      expect(c.carrierSuggestion!.name, 'Maersk');
      expect(c.carrierSuggestion!.label(arabic: true), 'ميرسك');
      expect(c.carrierSuggestion!.label(), 'Maersk');
    });

    test('tolerates missing and malformed fields', () {
      final c = ReferenceCheck.fromJson({'valid': true, 'suggestions': 'x', 'carrier_suggestion': 5});
      expect(c.valid, isTrue);
      expect(c.normalized, '');
      expect(c.suggestions, isEmpty);
      expect(c.carrierSuggestion, isNull);
      expect(ReferenceCheck.fromJson({}).valid, isFalse);
      expect(CarrierSuggestion.tryParse({'name_ar': 'x'}), isNull);
    });
  });

  group('MockTrackingRepository.validate', () {
    test('suggests look-alike fix and carrier', () async {
      final repo = MockTrackingRepository();
      final c = await repo.validate(ReferenceType.container, 'MSKU123456S');
      expect(c.valid, isFalse);
      expect(c.suggestions, isNotEmpty);
      expect(c.carrierSuggestion?.code, 'MAERSK');
      final ok = await repo.validate(ReferenceType.container, 'MSKU1234565');
      expect(ok.valid, isTrue);
      expect(ok.suggestions, isEmpty);
    });
  });

  testWidgets('add sheet shows suggestion chips and applies them', (tester) async {
    tester.view.physicalSize = const Size(1080, 4800);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [trackingRepositoryProvider.overrideWithValue(MockTrackingRepository())],
        child: const MaterialApp(home: Scaffold(body: AddShipmentSheet())),
      ),
    );
    await settle(tester, frames: 2);
    await tester.enterText(find.byType(TextField).first, 'MSKU123456S');
    await settle(tester, frames: 2);
    await tester.tap(find.widgetWithText(PrimaryButton, 'Start tracking'));
    await settle(tester, frames: 4);
    expect(find.text('Did you mean?'), findsOneWidget);
    final chip = find.byWidgetPredicate((w) =>
        w.key.toString().contains('ref_suggestion_'));
    expect(chip, findsWidgets);
    expect(find.byKey(const Key('carrier_suggestion')), findsOneWidget);

    await tester.tap(chip.first);
    await settle(tester, frames: 4);
    expect(find.text('Did you mean?'), findsNothing);
    // Reference now valid: carrier guess is refreshed and can be applied.
    await tester.tap(find.byKey(const Key('carrier_suggestion')));
    await settle(tester, frames: 2);
    expect(find.byKey(const Key('carrier_suggestion')), findsNothing);
    final carrierField = tester.widget<TextField>(find.byType(TextField).last);
    expect(carrierField.controller!.text, 'Maersk');
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 100));
  });
}
