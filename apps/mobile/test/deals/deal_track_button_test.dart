import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/deals/widgets/deal_track_button.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/add_shipment_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

/// Deals repo whose event log carries an optional shipment reference.
class _EventsRepo extends MockDealsRepository {
  _EventsRepo(this.data);

  final Map<String, dynamic> data;

  @override
  Future<DealEventList> events(String dealId) async => DealEventList(
        items: [
          DealEvent(seq: 1, action: 'fulfilment_started', actorRole: 'supplier', data: data),
        ],
        total: 1,
      );
}

Deal _deal({String status = kDealInFulfilment}) => Deal(
      id: 'deal_1',
      requestId: 'req_1',
      offerId: 'off_1',
      subtotal: const Money(amount: '1000.00', currency: 'USD'),
      commission: const Money(amount: '30.00', currency: 'USD'),
      status: status,
      createdAt: DateTime.utc(2026, 10, 14),
    );

Future<void> _pump(WidgetTester tester, DealsRepository repo) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = GoRouter(routes: [
    GoRoute(
      path: '/',
      builder: (_, __) => Scaffold(body: DealTrackButton(deal: _deal())),
    ),
    GoRoute(
      path: '/logistics/tracking/:id',
      builder: (_, s) => Scaffold(body: Text('detail:${s.pathParameters['id']}')),
    ),
  ]);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        dealsRepositoryProvider.overrideWithValue(repo),
        trackingRepositoryProvider.overrideWithValue(MockTrackingRepository()),
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await settle(tester, frames: 3);
}

Future<void> _unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  setUpWidgetTests();

  group('dealTrackingReference', () {
    test('newest event with a reference wins; blank and missing are ignored', () {
      final list = DealEventList(
        items: [
          DealEvent(seq: 1, action: 'a', actorRole: 'system', data: const {'reference': 'OLD123'}),
          DealEvent(seq: 2, action: 'b', actorRole: 'system', data: const {'tracking_reference': ' MSKU1234565 '}),
          DealEvent(seq: 3, action: 'c', actorRole: 'system', data: const {'tracking_reference': '  '}),
        ],
        total: 3,
      );
      expect(dealTrackingReference(list), 'MSKU1234565');
      expect(dealTrackingReference(DealEventList.empty), isNull);
    });

    test('button only for deals past payment', () {
      expect(dealHasShipment(_deal(status: kDealPendingPayment)), isFalse);
      expect(dealHasShipment(_deal(status: kDealPaid)), isTrue);
      expect(dealHasShipment(_deal()), isTrue);
      expect(dealHasShipment(_deal(status: kDealCompleted)), isTrue);
    });
  });

  group('DealTrackButton', () {
    testWidgets('tracked reference opens that shipment', (tester) async {
      await _pump(tester, _EventsRepo(const {'tracking_reference': 'MSKU1234565'}));
      expect(find.text('No shipment is linked to this deal yet. Add the container or AWB number to track it.'),
          findsNothing);
      await tester.tap(find.byKey(const Key('deal_track_shipment')));
      await settle(tester, frames: 4);
      expect(find.text('detail:shp_001'), findsOneWidget);
      await _unmount(tester);
    });

    testWidgets('untracked reference opens the add form prefilled', (tester) async {
      await _pump(tester, _EventsRepo(const {'tracking_reference': 'CSQU3054383'}));
      await tester.tap(find.byKey(const Key('deal_track_shipment')));
      await settle(tester, frames: 4);
      expect(find.byType(AddShipmentSheet), findsOneWidget);
      expect(find.widgetWithText(TextField, 'CSQU3054383'), findsOneWidget);
      await _unmount(tester);
    });

    testWidgets('no reference opens the empty add form with a hint', (tester) async {
      await _pump(tester, _EventsRepo(const {}));
      expect(find.text('No shipment is linked to this deal yet. Add the container or AWB number to track it.'),
          findsOneWidget);
      await tester.tap(find.byKey(const Key('deal_track_shipment')));
      await settle(tester, frames: 4);
      expect(find.byType(AddShipmentSheet), findsOneWidget);
      expect(find.widgetWithText(TextField, 'CSQU3054383'), findsNothing);
      await _unmount(tester);
    });
  });
}
