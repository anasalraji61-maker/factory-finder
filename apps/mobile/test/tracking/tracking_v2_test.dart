import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/tracking_detail_screen.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Shipment _fixture(String name) => Shipment.fromJson(Map<String, dynamic>.from(
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync()) as Map));

void main() {
  setUpWidgetTests();

  group('parsing optional fields', () {
    test('delayed shipment fixture', () {
      final s = _fixture('shipment_detail_delayed');
      expect(s.delayed, isTrue);
      expect(s.delayHours, 120);
      expect(s.initialEta, isNotNull);
      expect(s.warning, 'provider_unavailable:rate_limited');
      expect(s.milestones.keys, containsAll(['gate_in', 'loaded', 'departed']));
      expect(s.milestones['gate_in']!.isBefore(s.milestones['departed']!), isTrue);
    });

    test('old fixture has safe defaults and json round trips', () {
      final s = _fixture('shipment_detail');
      expect(s.delayed, isFalse);
      expect(s.delayHours, isNull);
      expect(s.warning, isNull);
      expect(s.milestones, isEmpty);
      final j = _fixture('shipment_detail_delayed').toJson();
      final back = Shipment.fromJson(Map<String, dynamic>.from(jsonDecode(jsonEncode(j)) as Map));
      expect(back.delayHours, 120);
      expect(back.milestones.length, 3);
    });

    test('warning key mapping', () {
      expect(trackingWarningKey('provider_unavailable:rate_limited'),
          'tracking.warning.rate_limited');
      expect(trackingWarningKey('provider_unavailable:weird'), 'tracking.warning.generic');
      expect(trackingWarningKey('something'), 'tracking.warning.generic');
    });
  });

  testWidgets('detail screen shows warning, delay and milestones', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final s = _fixture('shipment_detail_delayed');
    await tester.pumpWidget(
      ProviderScope(
        overrides: [shipmentProvider(s.id).overrideWith((ref) async => s)],
        child: MaterialApp(home: TrackingDetailScreen(shipmentId: s.id)),
      ),
    );
    await settle(tester, frames: 4);
    expect(find.byKey(const Key('tracking_warning')), findsOneWidget);
    expect(find.text('The tracking provider is rate limiting us. Try again later.'),
        findsOneWidget);
    expect(find.byKey(const Key('tracking_delay')), findsOneWidget);
    expect(find.text('Shipment delayed'), findsOneWidget);
    expect(find.textContaining('ETA slipped by about 5 days'), findsOneWidget);
    expect(find.byKey(const Key('milestone_gate_in')), findsOneWidget);
    expect(find.byKey(const Key('milestone_departed')), findsOneWidget);
    expect(find.byKey(const Key('milestone_delivered')), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 100));
  });

  testWidgets('plain shipment shows no banners', (tester) async {
    final s = _fixture('shipment_detail');
    await tester.pumpWidget(
      ProviderScope(
        overrides: [shipmentProvider(s.id).overrideWith((ref) async => s)],
        child: MaterialApp(home: TrackingDetailScreen(shipmentId: s.id)),
      ),
    );
    await settle(tester, frames: 4);
    expect(find.byKey(const Key('tracking_warning')), findsNothing);
    expect(find.byKey(const Key('tracking_delay')), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 100));
  });
}
