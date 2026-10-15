import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/add_shipment_sheet.dart';
import 'package:factory_finder/features/tracking/screens/tracking_detail_screen.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

/// Scriptable repository: no network, counts every call.
class FakeTrackingRepository implements TrackingRepository {
  FakeTrackingRepository({this.addError, this.refreshError, this.deleteError});

  Object? addError;
  Object? refreshError;
  Object? deleteError;
  int adds = 0;
  int refreshes = 0;
  final List<String> deleted = [];

  @override
  Future<Shipment> add(String reference, ReferenceType type, {String? carrier}) async {
    adds++;
    final e = addError;
    if (e != null) throw e;
    return Shipment(id: 'shp_new', reference: reference, referenceType: type);
  }

  @override
  Future<void> delete(String id) async {
    final e = deleteError;
    if (e != null) throw e;
    deleted.add(id);
  }

  @override
  Future<Shipment> refresh(String id) async {
    refreshes++;
    final e = refreshError;
    if (e != null) throw e;
    return Shipment(id: id, reference: 'X', referenceType: ReferenceType.container);
  }

  @override
  Future<Shipment> shipment(String id) async =>
      Shipment(id: id, reference: 'X', referenceType: ReferenceType.container);

  @override
  Future<List<Shipment>> shipments() async => const [];

  @override
  Future<ReferenceCheck> validate(ReferenceType type, String reference) async =>
      ReferenceCheck(valid: true, normalized: reference);

  @override
  Future<List<ReferenceCandidate>> detect(String query) async => const [];
}

ApiException _api(int status, String code) =>
    ApiException(status: status, code: code, message: code);

const String _longAr =
    'ميناء الملك عبد الله الاقتصادي الدولي المتفرع من منطقة رابغ الصناعية الكبرى، المملكة العربية السعودية';

Shipment _multiLeg() => Shipment.fromJson({
      'id': 'shp_ml',
      'reference': 'MSKU1234565',
      'reference_type': 'container',
      'status': 'exception',
      'eta': '2026-11-20T10:00:00Z',
      'initial_eta': '2026-11-10T10:00:00Z',
      'delayed': true,
      'delay_hours': 240,
      'origin': {'country_code': 'CN', 'city': _longAr},
      'destination': {'country_code': 'IQ', 'city': _longAr},
      'events': [
        {
          'status': 'departed',
          'description_ar': 'غادرت السفينة',
          'location': {'name': 'Ningbo', 'name_ar': _longAr},
          'timestamp': '2026-10-01T10:00:00Z',
          'vessel': {'name': 'MSC Aurora', 'voyage': '12W'},
        },
        {
          'status': 'transshipment',
          'description': 'Transshipped',
          'location': {'name': 'Jebel Ali', 'country_code': 'AE'},
          'timestamp': '2026-10-10T10:00:00Z',
          'vessel': {'name': 'Maersk Seletar', 'voyage': '77E'},
        },
        {
          'status': 'exception',
          'description': 'DELAYED: port congestion',
          'timestamp': '2026-10-12T10:00:00Z',
        },
        {
          'status': 'SOMETHING_NEW',
          'description': '',
          'timestamp': '2026-10-13T10:00:00Z',
        },
        {'status': 'damaged', 'timestamp': 'garbage'},
        'not-a-map',
      ],
    });

Future<void> _bigView(WidgetTester tester) async {
  tester.view.physicalSize = const Size(360, 3000) * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> _dispose(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
}

Widget _detail(Shipment s, {TrackingRepository? repo, bool arabic = false}) => ProviderScope(
      overrides: [
        shipmentProvider(s.id).overrideWith((ref) async => s),
        if (repo != null) trackingRepositoryProvider.overrideWithValue(repo),
      ],
      child: MaterialApp(
        locale: arabic ? const Locale('ar') : const Locale('en'),
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: TrackingDetailScreen(shipmentId: s.id),
      ),
    );

void main() {
  setUpWidgetTests();

  group('models', () {
    test('contract statuses and unknown values never crash', () {
      expect(ShipmentStatusX.parse('in_transit'), ShipmentStatus.inTransit);
      expect(ShipmentStatusX.parse('exception'), ShipmentStatus.exception);
      expect(ShipmentStatusX.parse('DELAYED'), ShipmentStatus.exception);
      expect(ShipmentStatusX.parse('Damaged'), ShipmentStatus.exception);
      expect(ShipmentStatusX.parse(' GATE_IN '), ShipmentStatus.gateIn);
      expect(ShipmentStatusX.parse('brand_new'), ShipmentStatus.unknown);
      expect(ShipmentStatusX.parse(null), ShipmentStatus.unknown);
      expect(ShipmentStatusX.parse(''), ShipmentStatus.unknown);
      for (final s in ShipmentStatus.values) {
        expect(ShipmentStatusX.parse(s.wire), s, reason: s.name);
        expect(s.defaultProgress, inInclusiveRange(0.0, 1.0));
        expect(statusKey(s), 'tracking.status.${s.wire}');
      }
    });

    test('multi-leg shipment parses tolerantly, newest first', () {
      final s = _multiLeg();
      expect(s.status, ShipmentStatus.exception);
      expect(s.events.length, 5); // the non-map entry is skipped
      expect(s.events.first.status, ShipmentStatus.unknown); // 2026-10-13
      final transship =
          s.events.firstWhere((e) => e.status == ShipmentStatus.transshipment);
      expect(transship.transport, 'Maersk Seletar · 77E');
      expect(transship.location, 'Jebel Ali');
      final departed = s.events.firstWhere((e) => e.status == ShipmentStatus.departed);
      expect(departed.location, _longAr);
      final garbage = s.events.last; // unparsable time sorts last
      expect(garbage.status, ShipmentStatus.exception);
      expect(garbage.hasTime, isFalse);
    });

    test('equal timestamps keep a deterministic order', () {
      Map<String, dynamic> ev(String d) =>
          {'status': 'loaded', 'description': d, 'timestamp': '2026-10-01T10:00:00Z'};
      final s = Shipment.fromJson({
        'id': 'a',
        'reference': 'R',
        'events': [ev('a'), ev('b'), ev('c'), ev('d')],
      });
      expect(s.events.map((e) => e.description).toList(), ['d', 'c', 'b', 'a']);
    });

    test('exception keeps progress of the last normal event', () {
      final s = Shipment.fromJson({
        'id': 'a',
        'reference': 'R',
        'status': 'exception',
        'events': [
          {'status': 'departed', 'timestamp': '2026-10-01T10:00:00Z'},
          {'status': 'exception', 'timestamp': '2026-10-02T10:00:00Z'},
        ],
      });
      expect(s.progressValue, ShipmentStatus.departed.defaultProgress);
      final server = Shipment.fromJson({'id': 'a', 'progress_percent': 250});
      expect(server.progressValue, 1.0);
    });

    test('missing id and null fields do not throw', () {
      final s = Shipment.fromJson({'status': null, 'events': null, 'origin': null});
      expect(s.id, '');
      expect(s.status, ShipmentStatus.unknown);
      expect(s.events, isEmpty);
    });
  });

  group('labels', () {
    test('UTC vs local dates are labelled', () {
      expect(utcOffsetLabel(DateTime.utc(2026, 10, 1)), 'UTC');
      expect(dateTimeLabel(DateTime.utc(2026, 10, 1, 9, 5)), contains('2026/10/01 09:05'));
      expect(dateTimeLabel(DateTime.utc(2026, 10, 1, 9, 5)), contains('(UTC)'));
      expect(dateTimeLabel(DateTime(2026, 10, 1, 9, 5)), contains('(UTC'));
    });

    test('add error mapping', () {
      expect(trackingAddErrorKey(_api(409, 'duplicate_shipment')), 'tracking.err.duplicate');
      expect(trackingAddErrorKey(_api(409, 'shipment_limit_reached')), 'tracking.err.limit');
      expect(trackingAddErrorKey(_api(422, 'invalid_reference')), 'tracking.err.invalid');
      expect(trackingAddErrorKey(_api(429, 'rate_limited')), 'error.rate_limited');
      expect(trackingAddErrorKey(_api(0, 'network_error')), 'tracking.err.offline');
      expect(trackingAddErrorKey(StateError('x')), 'tracking.err.generic');
    });
  });

  group('repository', () {
    test('mock delete removes the shipment and is idempotent', () async {
      final repo = MockTrackingRepository(clock: () => DateTime(2026, 10, 13, 12));
      await repo.delete('shp_001');
      await repo.delete('shp_001');
      expect(() => repo.shipment('shp_001'), throwsA(isA<ApiException>()));
    });
  });

  group('detail screen', () {
    testWidgets('multi-leg + exception + unknown status render at 360 (ar)', (tester) async {
      await _bigView(tester);
      final s = _multiLeg();
      await tester.pumpWidget(_detail(s, arabic: true));
      await settle(tester, frames: 4);
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('tracking_delay')), findsOneWidget);
      expect(find.text('DELAYED: port congestion'), findsOneWidget);
      expect(find.text('MSC Aurora · 12W'), findsOneWidget);
      // Event with empty description falls back to the status name.
      expect(find.byKey(const Key('timeline_title_0')), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('timeline_title_0'))).data,
          isNotEmpty);
      await _dispose(tester);
    });

    testWidgets('delayed shows original ETA; delivered shows the actual time',
        (tester) async {
      await _bigView(tester);
      await tester.pumpWidget(_detail(_multiLeg()));
      await settle(tester, frames: 4);
      expect(find.byKey(const Key('tracking_initial_eta')), findsOneWidget);
      expect(find.textContaining('ETA slipped by about 10 days'), findsOneWidget);
      await _dispose(tester);

      final delivered = Shipment.fromJson({
        'id': 'shp_d',
        'reference': 'MSKU1234565',
        'status': 'delivered',
        'eta': '2026-11-20T10:00:00Z',
        'initial_eta': '2026-11-10T10:00:00Z',
        'delayed': true,
        'delay_hours': 240,
        'milestones': {'delivered': '2026-11-22T08:00:00Z'},
      });
      await tester.pumpWidget(_detail(delivered));
      await settle(tester, frames: 4);
      expect(find.byKey(const Key('tracking_delivered_on')), findsOneWidget);
      expect(find.byKey(const Key('tracking_eta')), findsNothing);
      expect(find.byKey(const Key('tracking_delay')), findsNothing);
      await _dispose(tester);
    });

    testWidgets('empty events show the empty timeline text', (tester) async {
      await _bigView(tester);
      await tester.pumpWidget(_detail(
          Shipment(id: 's', reference: 'MSKU1234565', referenceType: ReferenceType.container)));
      await settle(tester, frames: 4);
      expect(find.text('No events yet'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('load failure shows a localized error with retry', (tester) async {
      await _bigView(tester);
      await tester.pumpWidget(ProviderScope(
        overrides: [
          shipmentProvider('x').overrideWith((ref) async => throw _api(404, 'not_found')),
        ],
        child: const MaterialApp(home: TrackingDetailScreen(shipmentId: 'x')),
      ));
      await settle(tester, frames: 4);
      expect(find.text('Retry'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('refresh is throttled client-side', (tester) async {
      await _bigView(tester);
      final repo = FakeTrackingRepository();
      await tester.pumpWidget(_detail(_multiLeg(), repo: repo));
      await settle(tester, frames: 4);
      await tester.tap(find.byIcon(Icons.refresh));
      await settle(tester, frames: 3);
      expect(repo.refreshes, 1);
      expect(find.text('Status updated'), findsOneWidget);
      await tester.tap(find.byIcon(Icons.refresh));
      await settle(tester, frames: 3);
      expect(repo.refreshes, 1);
      expect(find.text('Just updated, please wait a moment'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('refresh failure is surfaced and can be retried', (tester) async {
      await _bigView(tester);
      final repo = FakeTrackingRepository(refreshError: _api(502, 'upstream_error'));
      await tester.pumpWidget(_detail(_multiLeg(), repo: repo));
      await settle(tester, frames: 4);
      await tester.tap(find.byIcon(Icons.refresh));
      await settle(tester, frames: 3);
      expect(find.textContaining('Could not update the status'), findsOneWidget);
      expect(find.byIcon(Icons.refresh), findsOneWidget); // spinner gone
      await tester.tap(find.byIcon(Icons.refresh));
      await settle(tester, frames: 3);
      expect(repo.refreshes, 2); // failures do not start the cooldown
      await _dispose(tester);
    });

    testWidgets('delete asks for confirmation first', (tester) async {
      await _bigView(tester);
      final repo = FakeTrackingRepository();
      final s = _multiLeg();
      await tester.pumpWidget(_detail(s, repo: repo));
      await settle(tester, frames: 4);
      await tester.tap(find.byKey(const Key('tracking_delete')));
      await settle(tester, frames: 3);
      expect(find.text('Stop tracking this shipment?'), findsOneWidget);
      expect(find.textContaining('MSKU1234565'), findsWidgets);
      await tester.tap(find.byKey(const Key('tracking_delete_cancel')));
      await settle(tester, frames: 3);
      expect(repo.deleted, isEmpty);

      await tester.tap(find.byKey(const Key('tracking_delete')));
      await settle(tester, frames: 3);
      await tester.tap(find.byKey(const Key('tracking_delete_confirm')));
      await settle(tester, frames: 3);
      expect(repo.deleted, [s.id]);
      expect(find.text('Shipment deleted'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('delete failure keeps the screen and tells the user', (tester) async {
      await _bigView(tester);
      final repo = FakeTrackingRepository(deleteError: _api(500, 'boom'));
      await tester.pumpWidget(_detail(_multiLeg(), repo: repo));
      await settle(tester, frames: 4);
      await tester.tap(find.byKey(const Key('tracking_delete')));
      await settle(tester, frames: 3);
      await tester.tap(find.byKey(const Key('tracking_delete_confirm')));
      await settle(tester, frames: 3);
      expect(find.text('Could not delete the shipment'), findsOneWidget);
      expect(find.byKey(const Key('tracking_delete')), findsOneWidget);
      await _dispose(tester);
    });
  });

  group('add shipment sheet', () {
    Future<void> pumpSheet(WidgetTester tester, FakeTrackingRepository repo) async {
      await _bigView(tester);
      await tester.pumpWidget(ProviderScope(
        overrides: [trackingRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(home: Scaffold(body: AddShipmentSheet())),
      ));
      await settle(tester, frames: 3);
      await tester.enterText(find.byType(TextField).first, 'CSQU3054383');
      await tester.pump();
    }

    for (final c in <(Object, String)>[
      (_api(409, 'duplicate_shipment'), 'This reference is already in your shipments.'),
      (_api(409, 'shipment_limit_reached'),
          'You reached the tracked-shipment limit. Delete one to add another.'),
      (_api(422, 'invalid_reference'), 'The reference was rejected. Check it and try again.'),
      (_api(0, 'network_error'), 'No internet connection. Please try again.'),
      (StateError('x'), 'Could not add the shipment'),
    ]) {
      testWidgets('server error -> ${c.$2}', (tester) async {
        final repo = FakeTrackingRepository(addError: c.$1);
        await pumpSheet(tester, repo);
        await tester.tap(find.text('Start tracking'));
        await settle(tester, frames: 3);
        expect(find.text(c.$2), findsOneWidget);
        expect(repo.adds, 1);
        // Editing clears the stale server error and the form can be resubmitted.
        await tester.enterText(find.byType(TextField).first, 'MSKU1234565');
        await tester.pump();
        expect(find.text(c.$2), findsNothing);
        await _dispose(tester);
      });
    }

    testWidgets('invalid reference is rejected client-side without a request',
        (tester) async {
      final repo = FakeTrackingRepository();
      await pumpSheet(tester, repo);
      await tester.enterText(find.byType(TextField).first, 'CSQU3054384');
      await tester.tap(find.text('Start tracking'));
      await settle(tester, frames: 3);
      expect(repo.adds, 0);
      expect(find.textContaining('check digit failed'), findsOneWidget);
      await _dispose(tester);
    });
  });
}
