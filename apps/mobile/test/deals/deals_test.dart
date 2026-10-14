import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/deals/widgets/deal_lifecycle_section.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final ResponseBody Function(RequestOptions o) handler;
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object body, [int status = 200]) => ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

ApiClient _client(_FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = adapter;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

Deal _deal({String status = kDealPendingPayment}) => Deal(
      id: 'deal_1',
      requestId: 'req_1',
      offerId: 'off_1',
      subtotal: const Money(amount: '1000.00', currency: 'USD'),
      commission: const Money(amount: '30.00', currency: 'USD'),
      status: status,
      createdAt: DateTime.utc(2026, 10, 14),
    );

void main() {
  setUpWidgetTests();

  group('parsing', () {
    test('deal with payment, delivered_at and ids', () {
      final d = Deal.fromJson(Map<String, dynamic>.from(_load('deal_in_fulfilment') as Map));
      expect(d.status, kDealInFulfilment);
      expect(d.payment.commission, 'paid');
      expect(d.payment.dealPayment, 'paid');
      expect(d.deliveredAt, DateTime.utc(2026, 10, 14, 9, 30));
      expect(d.completedAt, isNull);
      expect(d.buyerId, startsWith('usr_'));
      expect(d.supplierUserId, startsWith('usr_'));
      expect(d.commission.amount, '45.00');
    });

    test('old deal json without new fields still parses', () {
      final d = Deal.fromJson({
        'id': 'deal_x',
        'subtotal': {'amount': '10', 'currency': 'USD'},
        'status': 'refunded',
      });
      expect(d.status, 'refunded');
      expect(d.payment.commission, isNull);
      expect(d.deliveredAt, isNull);
    });

    test('event list is sorted by seq and tolerant', () {
      final l = DealEventList.fromJson(_load('deal_events'));
      expect(l.total, 3);
      expect(l.items.map((e) => e.action),
          ['payment_paid', 'fulfilment_started', 'delivered']);
      expect(l.items.first.actorRole, 'system');
      expect(l.items.first.data['invoice_id'], 'inv_1');
      expect(DealEventList.fromJson(null).items, isEmpty);
      final e = DealEvent.fromJson({'seq': '2', 'action': 'new_thing'});
      expect(e.seq, 2);
      expect(e.actorRole, 'system');
      expect(e.fromStatus, isNull);
    });

    test('error mapping', () {
      ApiException ex(int s, String c) => ApiException(status: s, code: c, message: c);
      expect(dealErrorKey(ex(409, 'invalid_deal_transition')),
          'deals.err.invalid_deal_transition');
      expect(dealErrorKey(ex(403, 'supplier_verification_required')),
          'deals.err.supplier_verification_required');
      expect(dealErrorKey(ex(403, 'forbidden')), 'deals.err.forbidden');
      expect(dealErrorKey(ex(404, 'not_found')), 'deals.err.not_found');
      expect(dealErrorKey(ex(0, 'timeout')), 'deals.err.network');
      expect(dealErrorKey(StateError('x')), 'deals.err.generic');
    });

    test('role and actions', () {
      final d = Deal.fromJson(Map<String, dynamic>.from(_load('deal_in_fulfilment') as Map));
      final buyer = dealRoleFor(d, d.buyerId);
      final supplier = dealRoleFor(d, d.supplierUserId);
      expect(buyer, DealRole.buyer);
      expect(supplier, DealRole.supplier);
      expect(dealRoleFor(d, 'usr_other'), DealRole.none);
      expect(dealActionsFor(d, buyer).confirmReceipt, isTrue);
      expect(dealActionsFor(d, buyer).markDelivered, isFalse);
      // already delivered: supplier has nothing left to do
      expect(dealActionsFor(d, supplier).any, isFalse);
      final paid = d.copyWith(status: kDealPaid);
      expect(dealActionsFor(paid, supplier).startFulfilment, isTrue);
      expect(dealActionsFor(paid, buyer).any, isFalse);
    });
  });

  group('live repository', () {
    test('hits contract paths and parses', () async {
      final adapter = _FakeAdapter((o) {
        if (o.path.endsWith('/events')) return _json(_load('deal_events'));
        return _json(_load('deal_in_fulfilment'));
      });
      final repo = LiveDealsRepository(_client(adapter));
      final a = await repo.startFulfilment('deal_1');
      final b = await repo.markDelivered('deal_1');
      final c = await repo.confirmReceipt('deal_1');
      final ev = await repo.events('deal_1');
      await repo.get('deal_1');
      expect(adapter.calls.map((o) => '${o.method} ${o.path}').toList(), [
        'POST /v1/deals/deal_1/fulfilment/start',
        'POST /v1/deals/deal_1/delivered',
        'POST /v1/deals/deal_1/confirm-receipt',
        'GET /v1/deals/deal_1/events',
        'GET /v1/deals/deal_1',
      ]);
      expect(a.status, kDealInFulfilment);
      expect(b.deliveredAt, isNotNull);
      expect(c.id, startsWith('deal_'));
      expect(ev.items, hasLength(3));
    });

    test('409 and 403 error bodies become ApiException codes', () async {
      final adapter = _FakeAdapter((o) => o.path.contains('delivered')
          ? _json(_load('error_supplier_verification_required'), 403)
          : _json(_load('error_invalid_deal_transition'), 409));
      final repo = LiveDealsRepository(_client(adapter));
      await expectLater(
        repo.confirmReceipt('d'),
        throwsA(isA<ApiException>()
            .having((e) => e.status, 'status', 409)
            .having((e) => e.code, 'code', 'invalid_deal_transition')),
      );
      await expectLater(
        repo.markDelivered('d'),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'supplier_verification_required')),
      );
    });
  });

  group('mock state machine', () {
    test('happy path pending_payment -> completed with event log', () async {
      final repo = MockDealsRepository(clock: () => DateTime.utc(2026, 10, 14));
      repo.track(_deal());
      await expectLater(repo.startFulfilment('deal_1'), throwsA(isA<ApiException>()));
      final paid = await repo.simulatePayment('deal_1');
      expect(paid.status, kDealPaid);
      expect(paid.payment.dealPayment, 'paid');
      await expectLater(repo.confirmReceipt('deal_1'), throwsA(isA<ApiException>()));
      final started = await repo.startFulfilment('deal_1');
      expect(started.status, kDealInFulfilment);
      // idempotent: no duplicate event
      await repo.startFulfilment('deal_1');
      final delivered = await repo.markDelivered('deal_1');
      expect(delivered.deliveredAt, DateTime.utc(2026, 10, 14));
      expect(delivered.status, kDealInFulfilment);
      final done = await repo.confirmReceipt('deal_1');
      expect(done.status, kDealCompleted);
      expect(done.completedAt, isNotNull);
      expect((await repo.confirmReceipt('deal_1')).status, kDealCompleted);

      final events = (await repo.events('deal_1')).items;
      expect(events.map((e) => e.action).toList(), [
        'payment_paid',
        'fulfilment_started',
        'delivered',
        'receipt_confirmed',
      ]);
      expect(events.map((e) => e.seq).toList(), [1, 2, 3, 4]);
      expect(events.last.fromStatus, kDealInFulfilment);
      expect(events.last.toStatus, kDealCompleted);
    });

    test('wrong-state calls are 409 invalid_deal_transition; unknown deal 404', () async {
      final repo = MockDealsRepository();
      repo.track(_deal());
      Matcher conflict() => throwsA(isA<ApiException>()
          .having((e) => e.status, 'status', 409)
          .having((e) => e.code, 'code', 'invalid_deal_transition'));
      await expectLater(repo.markDelivered('deal_1'), conflict());
      await expectLater(repo.startFulfilment('deal_1'), conflict());
      await expectLater(repo.confirmReceipt('deal_1'), conflict());
      await expectLater(
        repo.get('nope'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)),
      );
    });
  });

  group('widgets', () {
    Future<void> pump(WidgetTester tester, MockDealsRepository repo, Deal deal,
        DealRole role) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [dealsRepositoryProvider.overrideWithValue(repo)],
          child: MaterialApp(
            home: Scaffold(
              body: Consumer(
                builder: (context, ref, _) => SingleChildScrollView(
                  child: DealLifecycleSection(deal: deal, role: role),
                ),
              ),
            ),
          ),
        ),
      );
      await settle(tester, frames: 3);
    }

    testWidgets('chips show payment states and events are listed', (tester) async {
      final repo = MockDealsRepository();
      final deal = _deal(status: kDealPaid)
          .copyWith(payment: const DealPayment(commission: 'paid', dealPayment: 'open'));
      repo.track(deal);
      await pump(tester, repo, deal, DealRole.buyer);
      expect(find.text('Paid'), findsOneWidget); // deal status chip
      expect(find.text('Commission: Paid'), findsOneWidget);
      expect(find.text('Supplier payment: Due'), findsOneWidget);
      expect(find.text('Waiting for the supplier to start fulfilment.'), findsOneWidget);
      expect(find.byKey(const Key('deal_start_fulfilment')), findsNothing);
      expect(find.byKey(const Key('deal_confirm_receipt')), findsNothing);
      expect(find.text('No events yet.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
    });

    testWidgets('supplier starts, delivers; buyer confirms via dialog', (tester) async {
      final repo = MockDealsRepository();
      final deal = _deal();
      repo.track(deal);
      await repo.simulatePayment(deal.id);
      final paid = await repo.get(deal.id);
      await pump(tester, repo, paid, DealRole.both);
      expect(find.byKey(const Key('deal_start_fulfilment')), findsOneWidget);
      expect(find.byKey(const Key('deal_confirm_receipt')), findsNothing);
      expect(find.text('Payment confirmed'), findsOneWidget);

      await tester.tap(find.byKey(const Key('deal_start_fulfilment')));
      await settle(tester, frames: 4);
      expect((await repo.get(deal.id)).status, kDealInFulfilment);
      expect(find.text('Fulfilment started'), findsOneWidget); // snackbar

      // Re-pump with the updated deal (the screen does this via the provider).
      final inFul = await repo.get(deal.id);
      await pump(tester, repo, inFul, DealRole.both);
      expect(find.byKey(const Key('deal_mark_delivered')), findsOneWidget);
      expect(find.byKey(const Key('deal_confirm_receipt')), findsOneWidget);
      expect(find.text('Supplier started fulfilment'), findsOneWidget);

      await tester.tap(find.byKey(const Key('deal_confirm_receipt')));
      await settle(tester, frames: 3);
      expect(find.text('Confirm you received the goods?'), findsOneWidget);
      await tester.tap(find.byKey(const Key('confirm_receipt_no')));
      await settle(tester, frames: 3);
      expect((await repo.get(deal.id)).status, kDealInFulfilment);

      await tester.tap(find.byKey(const Key('deal_confirm_receipt')));
      await settle(tester, frames: 3);
      await tester.tap(find.byKey(const Key('confirm_receipt_yes')));
      await settle(tester, frames: 4);
      expect((await repo.get(deal.id)).status, kDealCompleted);

      ScaffoldMessenger.of(tester.element(find.byType(Scaffold).first)).clearSnackBars();
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
      expect(tester.takeException(), isNull);
    });
  });
}
