import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:flutter_test/flutter_test.dart';

typedef _Handler = ResponseBody Function(RequestOptions options);

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final _Handler handler;
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

ApiClient _client(_FakeAdapter adapter, {TokenStore? tokens}) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = adapter;
  return ApiClient(
    baseUrl: 'http://fake',
    isMock: false,
    dio: dio,
    tokens: tokens,
  );
}

void main() {
  group('discover live', () {
    test('search uses /v1/search with contract params and parses the page', () async {
      final adapter = _FakeAdapter((o) => _json({
            'items': [mockListings.first.toJson(), mockListings[1].toJson()],
            'total': 2,
            'page': 1,
            'page_size': 50,
            'sources': [
              {'source': 'mock', 'status': 'ok', 'count': 2},
            ],
          }));
      final repo = DiscoverRepository(_client(adapter));
      final page = await repo.search(const ListingQuery(
        query: 'led',
        kind: ListingKind.product,
        condition: ItemCondition.used,
        maxMoq: 100,
        verifiedOnly: true,
        sort: SortOption.priceLow,
      ));
      final call = adapter.calls.single;
      expect(call.path, '/v1/search');
      expect(call.queryParameters['q'], 'led');
      expect(call.queryParameters['kind'], 'product');
      expect(call.queryParameters['condition'], 'used');
      expect(call.queryParameters['moq_max'], 100);
      expect(call.queryParameters['verified_only'], true);
      expect(page.items.length, 2);
      final prices = page.items.map((l) => l.price.min.value).toList();
      expect(prices[0] <= prices[1], isTrue);
    });

    test('listing, supplier, trust and categories paths', () async {
      final listing = mockListings.first;
      final adapter = _FakeAdapter((o) {
        if (o.path.startsWith('/v1/listings/')) return _json(listing.toJson());
        if (o.path.startsWith('/v1/suppliers/')) return _json(listing.supplier.toJson());
        if (o.path.startsWith('/v1/trust/suppliers/')) {
          return _json({
            'supplier_id': listing.supplier.id,
            'score': 81,
            'band': 'green',
            'factors': [
              {'key': 'verified', 'impact': 10, 'explanation': 'Verified'},
            ],
          });
        }
        if (o.path == '/v1/categories') {
          return _json([
            {
              'slug': 'product',
              'name': 'Products',
              'name_ar': 'منتجات',
              'children': [],
            },
          ]);
        }
        return _json({'error': {'code': 'not_found', 'message': 'nope'}}, 404);
      });
      final repo = DiscoverRepository(_client(adapter));
      expect((await repo.getListing(listing.id)).id, listing.id);
      expect((await repo.getSupplier(listing.supplier.id)).id, listing.supplier.id);
      final trust = await repo.getTrust(listing.supplier.id);
      expect(trust.score, 81);
      expect(trust.band, TrustBand.green);
      expect(trust.factors.single.explanationAr, isNull);
      final cats = await repo.categories();
      expect(cats.single.label('ar'), 'منتجات');
      expect(adapter.calls.map((c) => c.path), contains('/v1/trust/suppliers/${listing.supplier.id}'));
    });

    test('listing parser tolerates missing optional fields', () {
      final l = Listing.fromJson({
        'id': 'lst_x',
        'source': 'mock',
        'kind': 'product',
        'title': 'X',
        'price': {
          'min': {'amount': '1.5', 'currency': 'USD'},
          'max': {'amount': '2', 'currency': 'USD'},
        },
        'supplier': {
          'id': 'sup_x',
          'name': 'S',
          'location': {'country_code': 'CN'},
        },
      });
      expect(l.images, isEmpty);
      expect(l.moq, isNull);
      expect(l.supplier.trustBand, TrustBand.unknown);
    });

    test('errors map to ApiException with the contract code', () async {
      final adapter = _FakeAdapter((o) => _json(
            {'error': {'code': 'not_found', 'message': 'Listing missing'}},
            404,
          ));
      final repo = DiscoverRepository(_client(adapter));
      try {
        await repo.getListing('nope');
        fail('expected ApiException');
      } on ApiException catch (e) {
        expect(e.status, 404);
        expect(e.code, 'not_found');
        expect(e.message, 'Listing missing');
      }
    });
  });

  group('logistics live', () {
    final request = QuoteRequest(
      goodsValue: 10000,
      goodsCurrency: 'USD',
      weightKg: 2000,
      volumeM3: 8.5,
      hsCode: '851830',
      origin: const Location(countryCode: 'CN', city: 'Guangzhou'),
      destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
      incoterm: Incoterm.fob,
      displayCurrency: 'USD',
      modes: {TransportMode.seaLcl},
    );

    test('quote request JSON matches LandedCostRequest', () {
      final j = request.toJson();
      expect(
        j.keys.toSet(),
        {
          'goods',
          'origin',
          'destination',
          'supplier_incoterm',
          'display_currency',
          'insurance',
          'modes',
        },
      );
      final goods = j['goods'] as Map<String, dynamic>;
      expect(goods['total_value'], {'amount': '10000.00', 'currency': 'USD'});
      expect(goods['total_weight_kg'], '2000');
      expect(goods['total_volume_m3'], '8.5');
      expect(goods['hs_code'], '851830');
      expect(goods['dangerous_goods'], false);
      expect(j['supplier_incoterm'], 'FOB');
      expect(j['modes'], ['sea_lcl']);
      expect(j['destination'], {'country_code': 'IQ', 'city': 'Baghdad'});
    });

    test('posts to /v1/quotes/landed-cost and parses the quote', () async {
      final quote = MockQuoteGenerator.generate(request, lang: 'en');
      final adapter = _FakeAdapter((o) => _json(quote.toJson()));
      final repo = LogisticsRepository(_client(adapter));
      final result = await repo.calculate(request);
      final call = adapter.calls.single;
      expect(call.method, 'POST');
      expect(call.path, '/v1/quotes/landed-cost');
      expect((call.data as Map)['goods'], isA<Map>());
      expect(result.options.length, quote.options.length);
    });

    test('decimalString has no exponent or trailing zeros', () {
      expect(decimalString(12.5), '12.5');
      expect(decimalString(2000), '2000');
      expect(decimalString(0.0002), '0.0002');
    });
  });

  group('auth layer', () {
    test('attaches Bearer token and refreshes once on 401', () async {
      final tokens = TokenStore()..set('old-access', 'refresh-1');
      final adapter = _FakeAdapter((o) {
        if (o.path == '/v1/auth/refresh') {
          expect((o.data as Map)['refresh_token'], 'refresh-1');
          return _json({
            'access_token': 'new-access',
            'refresh_token': 'refresh-2',
            'token_type': 'bearer',
            'expires_in': 900,
          });
        }
        if (o.headers['Authorization'] == 'Bearer new-access') {
          return _json({'items': [], 'total': 0, 'page': 1, 'page_size': 50});
        }
        return _json({'error': {'code': 'unauthorized', 'message': 'expired'}}, 401);
      });
      final repo = RfqRepository(_client(adapter, tokens: tokens));
      final page = await repo.list(const RfqFilter(mine: true));
      expect(page.items, isEmpty);
      expect(tokens.accessToken, 'new-access');
      expect(tokens.refreshToken, 'refresh-2');
      final paths = adapter.calls.map((c) => c.path).toList();
      expect(paths, ['/v1/requests', '/v1/auth/refresh', '/v1/requests']);
      expect(adapter.calls.first.headers['Authorization'], 'Bearer old-access');
    });

    test('transient refresh failure (503) keeps the session', () async {
      final tokens = TokenStore()..set('a', 'r');
      final adapter = _FakeAdapter((o) {
        if (o.path == '/v1/auth/refresh') {
          return _json({'error': {'code': 'unavailable', 'message': 'down'}}, 503);
        }
        return _json({'error': {'code': 'unauthorized', 'message': 'no'}}, 401);
      });
      final repo = RfqRepository(_client(adapter, tokens: tokens));
      await expectLater(
        repo.list(const RfqFilter()),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 401)),
      );
      expect(tokens.refreshToken, 'r');
      expect(tokens.hasSession, isTrue);
    });

    test('ids that would escape the endpoint path are refused', () async {
      final adapter = _FakeAdapter((o) => _json({}));
      final client = _client(adapter);
      await expectLater(
        client.get('/v1/listings/../auth/me'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'bad_request')),
      );
      expect(adapter.calls, isEmpty);
    });

    test('failed refresh clears the session and surfaces 401', () async {
      final tokens = TokenStore()..set('a', 'r');
      var cleared = false;
      tokens.onCleared = () => cleared = true;
      final adapter = _FakeAdapter(
        (o) => _json({'error': {'code': 'unauthorized', 'message': 'no'}}, 401),
      );
      final repo = RfqRepository(_client(adapter, tokens: tokens));
      await expectLater(
        repo.list(const RfqFilter()),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 401)),
      );
      expect(tokens.hasSession, isFalse);
      expect(cleared, isTrue);
    });
  });

  group('rfq live', () {
    test('list, offers, create and accept use the rfq endpoints', () async {
      final req = buildMockRequests().first;
      final offer = buildMockOffers()[req.id]!.first;
      final adapter = _FakeAdapter((o) {
        if (o.method == 'GET' && o.path == '/v1/requests') {
          return _json({
            'items': [req.toJson()],
            'total': 1,
            'page': 1,
            'page_size': 50,
          });
        }
        if (o.method == 'GET' && o.path == '/v1/requests/${req.id}/offers') {
          return _json({
            'items': [offer.toJson()],
            'total': 1,
            'page': 1,
            'page_size': 50,
          });
        }
        if (o.method == 'POST' && o.path == '/v1/requests') {
          return _json(req.toJson(), 201);
        }
        if (o.method == 'POST' && o.path == '/v1/offers/${offer.id}/accept') {
          return _json({
            'id': 'deal_1',
            'request_id': req.id,
            'offer_id': offer.id,
            'subtotal': {'amount': '8900.00', 'currency': 'USD'},
            'commission': {
              'rate': '0.03',
              'amount': {'amount': '267.00', 'currency': 'USD'},
              'min_fee_applied': false,
            },
            'created_at': '2026-10-13T10:00:00Z',
          }, 201);
        }
        return _json({'error': {'code': 'not_found', 'message': 'x'}}, 404);
      });
      final repo = RfqRepository(_client(adapter));

      final page = await repo.list(
        const RfqFilter(mine: false),
      );
      expect(page.items.single.id, req.id);
      final q = adapter.calls.first.queryParameters;
      expect(q['scope'], 'public');
      expect(q.containsKey('status'), isFalse);

      final offers = await repo.offers(req.id);
      expect(offers.single.id, offer.id);

      final created = await repo.create(
        const RfqDraft(
          kind: ListingKind.product,
          title: 'LED lights',
          quantity: '200',
          unit: 'piece',
          destination: Location(countryCode: 'IQ', city: 'Baghdad'),
        ),
      );
      expect(created.id, req.id);
      final postBody = adapter.calls.firstWhere((c) => c.method == 'POST').data as Map;
      expect(postBody['title'], 'LED lights');
      expect(postBody['quantity'], '200');

      final deal = await repo.accept(offer);
      expect(deal.commission.amount, '267.00');
      expect(deal.commissionRate, '0.03');
      expect(deal.supplierNet, isNull);
    });
  });
}
