import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/data/rfq_validators.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

class _Adapter implements HttpClientAdapter {
  _Adapter(this.body);

  final Object body;
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return ResponseBody.fromString(jsonEncode(body), 200, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    });
  }

  @override
  void close({bool force = false}) {}
}

ApiClient _live(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

const Map<String, dynamic> _offerJson = {
  'id': 'off_9',
  'request_id': 'req_5',
  'supplier_user_id': 'u1',
  'supplier_name': 'Acme',
  'price': {'amount': '7.5', 'currency': 'USD'},
  'status': 'active',
  'created_at': '2026-10-15T00:00:00Z',
  'updated_at': '2026-10-15T00:00:00Z',
};

RfqRepository _mockRepo([MockRfqBackend? b]) => RfqRepository(
      ApiClient(baseUrl: 'http://fake', isMock: true),
      b ?? MockRfqBackend(),
    );

const OfferDraft _draft = OfferDraft(
  price: Money(amount: '7.5', currency: 'USD'),
  supplierName: 'Acme',
  moq: 100,
  leadTimeDays: 20,
  note: 'hello',
);

void main() {
  group('OfferDraft', () {
    test('toJson matches OfferCreate and omits empty optionals', () {
      expect(_draft.toJson(), {
        'price': {'amount': '7.5', 'currency': 'USD'},
        'supplier_name': 'Acme',
        'moq': 100,
        'lead_time_days': 20,
        'notes': 'hello',
      });
      final bare = const OfferDraft(
        price: Money(amount: '1', currency: 'EUR'),
        supplierName: 'X',
      ).toJson();
      expect(bare.keys.toSet(), {'price', 'supplier_name'});
    });
  });

  group('validators', () {
    test('price', () {
      expect(validateOfferPrice(''), 'req.err.price_required');
      expect(validateOfferPrice('0'), 'req.err.price_invalid');
      expect(validateOfferPrice('abc'), 'req.err.price_invalid');
      expect(validateOfferPrice('7.5'), isNull);
    });

    test('optional ints', () {
      expect(validateOfferInt(''), isNull);
      expect(validateOfferInt('20'), isNull);
      expect(validateOfferInt('-1'), 'req.err.int_invalid');
      expect(validateOfferInt('2.5'), 'req.err.int_invalid');
      expect(validateOfferInt('1000000001'), 'req.err.int_invalid');
    });

    test('supplier name', () {
      expect(validateOfferSupplierName('  '), 'req.err.supplier_name_required');
      expect(validateOfferSupplierName('Acme'), isNull);
    });
  });

  group('mock repository', () {
    test('submit adds my active offer and bumps the count', () async {
      final repo = _mockRepo();
      final o = await repo.submitOffer('req_005', _draft);
      expect(o.status, OfferStatus.active);
      expect(o.unitPrice.amount, '7.5');
      final mine = await repo.myOffers('req_005');
      expect(mine.map((e) => e.id), [o.id]);
      expect((await repo.get('req_005')).offerCount, 1);
    });

    test('second active offer is a 409; own request is a 403', () async {
      final repo = _mockRepo();
      await repo.submitOffer('req_005', _draft);
      await expectLater(
        repo.submitOffer('req_005', _draft),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 409)),
      );
      await expectLater(
        repo.submitOffer('req_001', _draft),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 403)),
      );
    });

    test('withdraw marks the offer withdrawn, then allows a new one', () async {
      final repo = _mockRepo();
      final o = await repo.submitOffer('req_005', _draft);
      final w = await repo.withdrawOffer(o);
      expect(w.status, OfferStatus.withdrawn);
      await expectLater(
        repo.withdrawOffer(o),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 409)),
      );
      final again = await repo.submitOffer('req_005', _draft);
      expect(again.status, OfferStatus.active);
    });
  });

  group('live repository', () {
    test('submitOffer POSTs the OfferCreate body', () async {
      final a = _Adapter(_offerJson);
      final o = await RfqRepository(_live(a)).submitOffer('req_5', _draft);
      expect(o.id, 'off_9');
      expect(a.calls.single.method, 'POST');
      expect(a.calls.single.path, '/v1/requests/req_5/offers');
      expect((a.calls.single.data as Map)['supplier_name'], 'Acme');
    });

    test('withdrawOffer POSTs to /v1/offers/{id}/withdraw', () async {
      final a = _Adapter({..._offerJson, 'status': 'withdrawn'});
      final offer = Offer.fromJson(_offerJson);
      final o = await RfqRepository(_live(a)).withdrawOffer(offer);
      expect(o.status, OfferStatus.withdrawn);
      expect(a.calls.single.method, 'POST');
      expect(a.calls.single.path, '/v1/offers/off_9/withdraw');
    });

    test('myOffers GETs the request offers page', () async {
      final a = _Adapter({
        'items': [_offerJson],
        'total': 1,
        'page': 1,
        'page_size': 20,
      });
      final list = await RfqRepository(_live(a)).myOffers('req_5');
      expect(list.single.supplierName, 'Acme');
      expect(a.calls.single.method, 'GET');
      expect(a.calls.single.path, '/v1/requests/req_5/offers');
    });
  });

  group('seller screens', () {
    testWidgets('open requests list shows other buyers requests', (tester) async {
      await pumpApp(
        tester,
        location: '/requests/open',
        overrides: [rfqRepositoryProvider.overrideWithValue(_mockRepo())],
      );
      await settle(tester, frames: 12);
      expect(find.byKey(const ValueKey<String>('open-req-req_005')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('open-req-req_001')), findsNothing);
      await disposeApp(tester);
    });

    testWidgets('submit then withdraw an offer', (tester) async {
      await pumpApp(
        tester,
        logicalSize: const Size(540, 2400),
        location: '/requests/req_005/offer',
        overrides: [rfqRepositoryProvider.overrideWithValue(_mockRepo())],
      );
      await settle(tester, frames: 12);
      await tester.enterText(find.byKey(const ValueKey<String>('offer-supplier')), 'Acme');
      await tester.enterText(find.byKey(const ValueKey<String>('offer-price')), '7.5');
      await tester.enterText(find.byKey(const ValueKey<String>('offer-moq')), '100');
      await tester.enterText(find.byKey(const ValueKey<String>('offer-lead')), '20');
      final submit = find.byKey(const ValueKey<String>('offer-submit'));
      await tester.ensureVisible(submit);
      await tester.tap(submit);
      await settle(tester, frames: 16);

      final withdraw = find.byKey(const ValueKey<String>('offer-withdraw-off_101'));
      expect(withdraw, findsOneWidget);
      expect(submit, findsNothing);

      await tester.ensureVisible(withdraw);
      await tester.tap(withdraw);
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey<String>('offer-withdraw-confirm')));
      await settle(tester, frames: 16);

      expect(withdraw, findsNothing);
      expect(find.byKey(const ValueKey<String>('offer-submit')), findsOneWidget);
      await disposeApp(tester);
    });

    testWidgets('invalid price blocks submit', (tester) async {
      final backend = MockRfqBackend();
      await pumpApp(
        tester,
        logicalSize: const Size(540, 2400),
        location: '/requests/req_005/offer',
        overrides: [rfqRepositoryProvider.overrideWithValue(_mockRepo(backend))],
      );
      await settle(tester, frames: 12);
      await tester.enterText(find.byKey(const ValueKey<String>('offer-supplier')), 'Acme');
      final submit = find.byKey(const ValueKey<String>('offer-submit'));
      await tester.ensureVisible(submit);
      await tester.tap(submit);
      await settle(tester, frames: 12);
      expect(backend.offers['req_005'], isNull);
      await disposeApp(tester);
    });
  });
}
