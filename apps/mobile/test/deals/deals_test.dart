import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/deals/screens/deals_list_screen.dart';
import 'package:factory_finder/features/deals/widgets/deal_lifecycle_section.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
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

    test('deals page parses via PageResult', () {
      final p = PageResult.fromJson<Deal>(
        Map<String, dynamic>.from(_load('deals_page') as Map),
        Deal.fromJson,
      );
      expect(p.total, 3);
      expect(p.pageSize, 2);
      expect(p.items.map((d) => d.status), [kDealInFulfilment, kDealPaid]);
      expect(p.items.last.deliveredAt, isNull);
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

    test('listDeals sends role/status/paging query and parses the page', () async {
      final adapter = _FakeAdapter((o) => _json(_load('deals_page')));
      final repo = LiveDealsRepository(_client(adapter));
      final page = await repo.listDeals(role: 'supplier', status: 'paid', page: 2, pageSize: 2);
      final o = adapter.calls.single;
      expect(o.method, 'GET');
      expect(o.path, '/v1/deals');
      expect(o.queryParameters, {
        'role': 'supplier',
        'status': 'paid',
        'page': 2,
        'page_size': 2,
      });
      expect(page.items, hasLength(2));
      expect(page.total, 3);
      await repo.listDeals();
      expect(adapter.calls.last.queryParameters.containsKey('status'), isFalse);
      expect(adapter.calls.last.queryParameters['role'], 'any');
    });

    test('dealForRequest returns the deal, null on 404, rethrows others', () async {
      var mode = 200;
      final adapter = _FakeAdapter((o) {
        if (mode == 200) return _json(_load('deal_in_fulfilment'));
        if (mode == 404) return _json({'error': {'code': 'not_found', 'message': 'nope'}}, 404);
        return _json({'error': {'code': 'internal', 'message': 'boom'}}, 500);
      });
      final repo = LiveDealsRepository(_client(adapter));
      final d = await repo.dealForRequest('req_1');
      expect(d?.status, kDealInFulfilment);
      expect(adapter.calls.single.path, '/v1/requests/req_1/deal');
      mode = 404;
      expect(await repo.dealForRequest('req_1'), isNull);
      mode = 500;
      await expectLater(
        repo.dealForRequest('req_1'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 500)),
      );
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

  group('mock list', () {
    test('filters by status, pages newest first, dealForRequest', () async {
      final repo = MockDealsRepository();
      Deal mk(String id, String status, int day) => Deal(
            id: id,
            requestId: 'r_$id',
            offerId: 'o',
            subtotal: const Money(amount: '10', currency: 'USD'),
            commission: const Money(amount: '1', currency: 'USD'),
            status: status,
            createdAt: DateTime.utc(2026, 10, day),
          );
      repo.track(mk('a', kDealPaid, 1));
      repo.track(mk('b', kDealPendingPayment, 2));
      repo.track(mk('c', kDealPaid, 3));
      final p1 = await repo.listDeals(page: 1, pageSize: 2);
      expect(p1.items.map((d) => d.id), ['c', 'b']);
      expect(p1.total, 3);
      final p2 = await repo.listDeals(page: 2, pageSize: 2);
      expect(p2.items.map((d) => d.id), ['a']);
      final paid = await repo.listDeals(status: kDealPaid);
      expect(paid.items.map((d) => d.id), ['c', 'a']);
      expect((await repo.listDeals(page: 9)).items, isEmpty);
      expect((await repo.dealForRequest('r_b'))?.id, 'b');
      expect(await repo.dealForRequest('zzz'), isNull);
    });
  });

  group('list screen', () {
    Deal mk(String id, String status, {String? supplier}) => Deal(
          id: id,
          requestId: 'r_$id',
          offerId: 'o',
          subtotal: const Money(amount: '10', currency: 'USD'),
          commission: const Money(amount: '1', currency: 'USD'),
          status: status,
          supplierUserId: supplier,
          createdAt: DateTime.utc(2026, 10, 14),
        );

    Future<void> pumpList(WidgetTester tester, DealsRepository repo) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [dealsRepositoryProvider.overrideWithValue(repo)],
          child: const MaterialApp(
            supportedLocales: [Locale('ar'), Locale('en')],
            locale: Locale('en'),
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            home: DealsListScreen(),
          ),
        ),
      );
      await settle(tester, frames: 4);
    }

    testWidgets('role tabs and status filter drive the repository', (tester) async {
      final repo = _RecordingRepo();
      await pumpList(tester, repo);
      expect(repo.calls.last, 'buyer/null/1');
      expect(find.byKey(const Key('deal_tile_d1')), findsOneWidget);
      expect(find.byKey(const Key('deals_load_more')), findsOneWidget);

      await tester.ensureVisible(find.byKey(const Key('deals_load_more')));
      await tester.tap(find.byKey(const Key('deals_load_more')));
      await settle(tester, frames: 4);
      expect(repo.calls.last, 'buyer/null/2');
      expect(find.byKey(const Key('deal_tile_d2')), findsOneWidget);
      expect(find.byKey(const Key('deals_load_more')), findsNothing);

      await tester.tap(find.byKey(const Key('deals_tab_supplier')));
      await settle(tester, frames: 6);
      expect(repo.calls.last, 'supplier/null/1');

      await tester.ensureVisible(find.byKey(const Key('deals_filter_paid')));
      await tester.tap(find.byKey(const Key('deals_filter_paid')));
      await settle(tester, frames: 4);
      expect(repo.calls.last, 'supplier/paid/1');
      expect(find.byKey(const Key('deals_empty')), findsOneWidget);
      expect(find.text('No deals with this status.'), findsOneWidget);

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
      expect(tester.takeException(), isNull);
    });

    testWidgets('error state offers retry', (tester) async {
      final repo = _RecordingRepo(fail: true);
      await pumpList(tester, repo);
      expect(find.byKey(const Key('deals_error')), findsOneWidget);
      repo.fail = false;
      await tester.tap(find.text('Retry'));
      await settle(tester, frames: 4);
      expect(find.byKey(const Key('deals_error')), findsNothing);
      expect(find.byKey(const Key('deal_tile_d1')), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
    });

    testWidgets('mock repo empty state', (tester) async {
      await pumpList(tester, MockDealsRepository());
      expect(find.text('No deals yet'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(milliseconds: 100));
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

/// Two-page fake: page 1 has d1 (total 2, page size 1), page 2 has d2;
/// role supplier + status filter returns nothing.
class _RecordingRepo extends MockDealsRepository {
  _RecordingRepo({this.fail = false});

  bool fail;
  final List<String> calls = <String>[];

  @override
  Future<PageResult<Deal>> listDeals({
    String role = 'any',
    String? status,
    int page = 1,
    int pageSize = 20,
  }) async {
    calls.add('$role/$status/$page');
    if (fail) {
      throw ApiException(status: 500, code: 'internal', message: 'boom');
    }
    Deal mk(String id) => Deal(
          id: id,
          requestId: 'r_$id',
          offerId: 'o',
          subtotal: const Money(amount: '10', currency: 'USD'),
          commission: const Money(amount: '1', currency: 'USD'),
          createdAt: DateTime.utc(2026, 10, 14),
        );
    if (status != null) {
      return PageResult<Deal>(items: <Deal>[], total: 0, page: page, pageSize: 1);
    }
    return PageResult<Deal>(
      items: <Deal>[mk(page == 1 ? 'd1' : 'd2')],
      total: 2,
      page: page,
      pageSize: 1,
    );
  }
}
