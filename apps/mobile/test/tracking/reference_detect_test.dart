import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/tracking/data/reference_validators.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/add_shipment_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

class _Rec implements HttpClientAdapter {
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return ResponseBody.fromString(
      jsonEncode(<String, Object?>{
        'candidates': <Object?>[
          <String, Object?>{'type': 'awb', 'confidence': 'medium', 'normalized': 'x', 'note': 'n'},
          <String, Object?>{'type': 'bogus', 'confidence': 'high', 'normalized': 'x', 'note': 'n'},
        ],
      }),
      200,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _Counting extends MockTrackingRepository {
  final List<String> queries = <String>[];
  Object? error;

  @override
  Future<List<ReferenceCandidate>> detect(String query) async {
    queries.add(query);
    if (error != null) throw error!;
    return super.detect(query);
  }
}

Future<void> _mount(WidgetTester tester, TrackingRepository repo) async {
  tester.view.physicalSize = const Size(1080, 4800);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [trackingRepositoryProvider.overrideWithValue(repo)],
      child: const MaterialApp(home: Scaffold(body: AddShipmentSheet())),
    ),
  );
  await settle(tester, frames: 2);
}

void main() {
  setUpWidgetTests();

  group('detection data', () {
    test('local detection is deterministic', () {
      final c = detectReferenceLocally('msku 123456-5');
      expect(c.map((e) => e.type), contains(ReferenceType.container));
      expect(c.every((e) => e.confidence == DetectConfidence.medium), isTrue);
      final imo = detectReferenceLocally('9074729');
      expect(imo.map((e) => e.type), containsAll([ReferenceType.vesselImo, ReferenceType.bl]));
      final bl = detectReferenceLocally('ABCDEF123');
      expect(bl.single.type, ReferenceType.bl);
      expect(bl.single.confidence, DetectConfidence.high);
      expect(detectReferenceLocally('ab'), isEmpty);
      expect(detectReferenceLocally(''), isEmpty);
    });

    test('live repository calls GET /v1/references/detect and skips unknown types', () async {
      final rec = _Rec();
      final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = rec;
      final repo = LiveTrackingRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
      final out = await repo.detect('17612345675');
      expect(rec.calls.single.method, 'GET');
      expect(rec.calls.single.path, '/v1/references/detect');
      expect(rec.calls.single.queryParameters['q'], '17612345675');
      expect(out.single.type, ReferenceType.awb);
      expect(out.single.confidence, DetectConfidence.medium);
    });
  });

  group('add sheet', () {
    testWidgets('debounces 400 ms, needs 4 chars and shows probable chips', (tester) async {
      final repo = _Counting();
      await _mount(tester, repo);
      await tester.enterText(find.byType(TextField).first, 'MSK');
      await tester.pump(const Duration(milliseconds: 500));
      expect(repo.queries, isEmpty);

      await tester.enterText(find.byType(TextField).first, 'MSKU1');
      await tester.pump(const Duration(milliseconds: 200));
      await tester.enterText(find.byType(TextField).first, 'MSKU1234565');
      await tester.pump(const Duration(milliseconds: 300));
      expect(repo.queries, isEmpty);
      await tester.pump(const Duration(milliseconds: 200));
      await settle(tester, frames: 2);
      expect(repo.queries, ['MSKU1234565']);
      expect(find.byKey(const Key('detected_container')), findsOneWidget);
      expect(find.text('Probably: Container'), findsOneWidget);

      await tester.enterText(find.byType(TextField).first, 'ab');
      await settle(tester, frames: 2);
      expect(find.byKey(const Key('detected_container')), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
    });

    testWidgets('a failing detection never blocks submitting', (tester) async {
      final repo = _Counting()..error = StateError('down');
      await _mount(tester, repo);
      await tester.enterText(find.byType(TextField).first, 'MSKU1234565');
      await tester.pump(const Duration(milliseconds: 450));
      await settle(tester, frames: 2);
      expect(repo.queries, hasLength(1));
      expect(find.byKey(const Key('detected_container')), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
    });
  });
}
