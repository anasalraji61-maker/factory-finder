import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter_test/flutter_test.dart';

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final ResponseBody Function(RequestOptions options) handler;
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

ApiClient _live(_FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = adapter;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

ProductDraft _valid() => const ProductDraft(
      title: 'LED Panel',
      category: 'lighting',
      priceMin: '2.50',
      priceMax: '4',
    );

void main() {
  group('validation', () {
    test('minimal valid draft has no errors', () {
      expect(validateProductDraft(_valid()), isEmpty);
    });

    test('required fields and limits', () {
      final e = validateProductDraft(const ProductDraft());
      expect(e['title'], 'myp.err.title_required');
      expect(e['category'], 'myp.err.category_required');
      expect(e['priceMin'], 'myp.err.price_invalid');
      expect(e['priceMax'], 'myp.err.price_invalid');

      expect(
        validateProductDraft(ProductDraft(title: 'ab', category: 'c', priceMin: '1', priceMax: '1'))['title'],
        'myp.err.title_length',
      );
      expect(
        validateProductDraft(ProductDraft(title: 'x' * 141, category: 'c', priceMin: '1', priceMax: '1'))['title'],
        'myp.err.title_length',
      );
      expect(
        validateProductDraft(ProductDraft(
          title: 'abc',
          category: 'c',
          priceMin: '1',
          priceMax: '1',
          description: 'd' * 4001,
        ))['description'],
        'myp.err.description_long',
      );
    });

    test('price range is compared exactly and money must be positive decimals', () {
      ProductDraft p(String a, String b) =>
          ProductDraft(title: 'abc', category: 'c', priceMin: a, priceMax: b);
      expect(validateProductDraft(p('4', '2.5'))['priceMax'], 'myp.err.price_range');
      expect(validateProductDraft(p('2.50', '2.5')), isEmpty);
      expect(validateProductDraft(p('0', '1'))['priceMin'], 'myp.err.price_invalid');
      expect(validateProductDraft(p('1e3', '2000'))['priceMin'], 'myp.err.price_invalid');
      expect(validateProductDraft(p('-1', '2'))['priceMin'], 'myp.err.price_invalid');
      expect(validateProductDraft(p('١٫٥', '٢'))['priceMin'], isNull);
      expect(compareDecimalStrings('0.1', '0.10'), 0);
      expect(compareDecimalStrings('10', '9.99') > 0, isTrue);
      expect(compareDecimalStrings('0.30000000000000004', '0.3') > 0, isTrue);
      expect(compareDecimalStrings('007', '7'), 0);
    });

    test('moq, hs code, lead time, numbers', () {
      ProductDraft d({String moq = '1', String hs = '', String lo = '', String hi = '', String w = ''}) =>
          ProductDraft(
            title: 'abc',
            category: 'c',
            priceMin: '1',
            priceMax: '1',
            moq: moq,
            hsCode: hs,
            leadMin: lo,
            leadMax: hi,
            unitWeightKg: w,
          );
      expect(validateProductDraft(d(moq: '0'))['moq'], 'myp.err.moq_invalid');
      expect(validateProductDraft(d(moq: '1.5'))['moq'], 'myp.err.moq_invalid');
      expect(validateProductDraft(d(moq: ''))['moq'], 'myp.err.moq_invalid');
      expect(validateProductDraft(d(hs: '12345'))['hs'], 'myp.err.hs_invalid');
      expect(validateProductDraft(d(hs: '12345678901'))['hs'], 'myp.err.hs_invalid');
      expect(validateProductDraft(d(hs: '9405.42')), isEmpty);
      expect(validateProductDraft(d(hs: '94054a'))['hs'], 'myp.err.hs_invalid');
      expect(validateProductDraft(d(lo: '10'))['lead'], 'myp.err.lead_invalid');
      expect(validateProductDraft(d(lo: '20', hi: '10'))['lead'], 'myp.err.lead_invalid');
      expect(validateProductDraft(d(lo: '10', hi: '20')), isEmpty);
      expect(validateProductDraft(d(w: '0'))['weight'], 'myp.err.number_invalid');
      expect(validateProductDraft(d(w: '0.5')), isEmpty);
    });

    test('images: http(s) only, at most 8', () {
      expect(isValidImageUrl('https://a.com/x.jpg'), isTrue);
      expect(isValidImageUrl('http://a.com'), isTrue);
      expect(isValidImageUrl('ftp://a.com/x'), isFalse);
      expect(isValidImageUrl('a.com/x.jpg'), isFalse);
      expect(isValidImageUrl('https://'), isFalse);
      expect(isValidImageUrl('https://a.com/a b.jpg'), isFalse);
      ProductDraft withImages(List<String> i) => ProductDraft(
            title: 'abc',
            category: 'c',
            priceMin: '1',
            priceMax: '1',
            images: i,
          );
      expect(validateProductDraft(withImages(['https://a.com/1'])), isEmpty);
      expect(validateProductDraft(withImages(['nope']))['images'], 'myp.err.image_url');
      expect(
        validateProductDraft(withImages([for (var i = 0; i < 9; i++) 'https://a.com/$i']))['images'],
        'myp.err.images_many',
      );
      expect(
        validateProductDraft(withImages([for (var i = 0; i < 8; i++) 'https://a.com/$i'])),
        isEmpty,
      );
    });
  });

  group('request body', () {
    test('minimal body keeps money as strings and omits empty optionals', () {
      final body = buildListingBody(_valid());
      expect(body, <String, dynamic>{
        'kind': 'product',
        'condition': 'new',
        'title': 'LED Panel',
        'category': 'lighting',
        'price': {
          'min': {'amount': '2.50', 'currency': 'USD'},
          'max': {'amount': '4', 'currency': 'USD'},
        },
        'unit': 'piece',
        'moq': 1,
        'origin': {'country_code': 'IQ'},
      });
      expect(jsonEncode(body), contains('"amount":"2.50"'));
    });

    test('full body', () {
      final body = buildListingBody(const ProductDraft(
        kind: ListingKind.rawMaterial,
        condition: ItemCondition.used,
        title: ' Steel coils ',
        titleAr: 'صلب',
        description: 'desc',
        descriptionAr: 'وصف',
        category: 'metals',
        priceMin: '١٫٥',
        priceMax: '2,75',
        currency: 'EUR',
        unit: 'ton',
        moq: '5',
        incoterm: Incoterm.cif,
        unitWeightKg: '0.5',
        unitVolumeM3: '0.01',
        hsCode: '9405.42',
        leadMin: '10',
        leadMax: '20',
        images: ['https://a.com/1.jpg'],
        origin: Location(countryCode: 'iq', city: ' Basra '),
      ));
      expect(body['kind'], 'raw_material');
      expect(body['title'], 'Steel coils');
      expect(body['title_ar'], 'صلب');
      expect(body['description'], 'desc');
      expect(body['description_ar'], 'وصف');
      expect(body['price'], {
        'min': {'amount': '1.5', 'currency': 'EUR'},
        'max': {'amount': '2.75', 'currency': 'EUR'},
      });
      expect(body['moq'], 5);
      expect(body['incoterm'], 'CIF');
      expect(body['unit_weight_kg'], 0.5);
      expect(body['unit_volume_m3'], 0.01);
      expect(body['hs_code'], '940542');
      expect(body['lead_time_days'], {'min': 10, 'max': 20});
      expect(body['images'], ['https://a.com/1.jpg']);
      expect(body['origin'], {'country_code': 'IQ', 'city': 'Basra'});
    });
  });

  group('error mapping', () {
    ApiException e(String code, [int? status]) =>
        ApiException(status: status, code: code, message: 'm');

    test('known server codes', () {
      expect(myProductsErrorKey(e('supplier_required', 403)), 'myp.err.supplier_required');
      expect(myProductsErrorKey(e('validation_error', 422)), 'myp.err.server_validation');
      expect(myProductsErrorKey(e('listing_cap_reached', 409)), 'myp.err.cap_reached');
      expect(myProductsErrorKey(e('not_published', 409)), 'myp.err.not_published');
      expect(myProductsErrorKey(e('trust_blocked', 403)), 'myp.err.trust_blocked');
      expect(myProductsErrorKey(e('trust_unavailable', 503)), 'myp.err.trust_unavailable');
      expect(myProductsErrorKey(e('rate_limited', 429)), 'myp.err.rate_limited');
      expect(myProductsErrorKey(e('timeout')), 'myp.err.network');
    });

    test('falls back on status, then generic', () {
      expect(myProductsErrorKey(e('http_422', 422)), 'myp.err.server_validation');
      expect(myProductsErrorKey(e('http_429', 429)), 'myp.err.rate_limited');
      expect(myProductsErrorKey(e('http_500', 500)), 'myp.err.generic');
      expect(myProductsErrorKey(Exception('x')), 'myp.err.generic');
    });
  });

  group('parsing', () {
    test('live fixture page', () {
      final json = jsonDecode(File('test/fixtures/live/my_listings.json').readAsStringSync());
      final page = parseOwnedPage(json);
      expect(page.total, 2);
      expect(page.pageSize, 20);
      expect(page.items, hasLength(2));
      final a = page.items[0];
      expect(a.id, 'lst_my_0001');
      expect(a.status, ListingStatus.draft);
      expect(a.kind, ListingKind.product);
      expect(a.price.min.amount, '2.50');
      expect(a.price.max.currency, 'USD');
      expect(a.incoterm, Incoterm.fob);
      expect(a.unitWeightKg, 3.2);
      expect(a.hsCode, '940542');
      expect(a.leadTimeDays?.max, 20);
      expect(a.origin?.city, 'Baghdad');
      expect(a.publishedAt, isNull);
      expect(a.createdAt, isNotNull);
      final b = page.items[1];
      expect(b.status, ListingStatus.published);
      expect(b.condition, ItemCondition.used);
      expect(b.moq, 5);
      expect(b.price.max.amount, '650.5');
      expect(b.incoterm, isNull);
      expect(b.origin, isNull);
      expect(b.publishedAt, isNotNull);
      expect(b.displayTitle('ar'), 'Steel coils');
      expect(a.displayTitle('ar'), 'إضاءة LED لوح');
    });

    test('tolerates garbage', () {
      expect(parseOwnedPage(null).items, isEmpty);
      expect(parseOwnedPage({'items': [1, 'x', {}]}).items, hasLength(1));
      final l = OwnedListing.fromJson({'id': 5, 'status': 'weird'});
      expect(l.id, '5');
      expect(l.status, ListingStatus.draft);
      expect(l.price.min.amount, '0');
    });

    test('toDraft round trips into a valid body', () {
      final json = jsonDecode(File('test/fixtures/live/my_listings.json').readAsStringSync());
      final draft = parseOwnedPage(json).items.first.toDraft();
      expect(validateProductDraft(draft), isEmpty);
      final body = buildListingBody(draft);
      expect(body['price'], {
        'min': {'amount': '2.50', 'currency': 'USD'},
        'max': {'amount': '4.00', 'currency': 'USD'},
      });
    });
  });

  group('categories', () {
    test('leaves per kind come from the tree, with a built-in fallback', () {
      expect(
        leafCategoriesFor(kFallbackCategories, ListingKind.rawMaterial).map((n) => n.slug),
        contains('metals'),
      );
      expect(leafCategoriesFor(const [], ListingKind.productionLine), isNotEmpty);
      expect(
        leafCategoriesFor(const [
          CategoryNode(slug: 'product', name: 'P', nameAr: 'P', children: [
            CategoryNode(slug: 'only_leaf', name: 'L', nameAr: 'L'),
          ]),
        ], ListingKind.product).map((n) => n.slug),
        ['only_leaf'],
      );
    });
  });

  group('mock repository', () {
    test('create, list by status, publish, unpublish, delete', () async {
      final repo = MyListingsRepository(ApiClient(baseUrl: 'http://x', isMock: true));
      final created = await repo.create(_valid());
      expect(created.status, ListingStatus.draft);
      expect(created.price.min.amount, '2.50');

      var drafts = await repo.list(status: ListingStatus.draft);
      expect(drafts.items.map((l) => l.id), [created.id]);

      try {
        await repo.unpublish(created.id);
        fail('expected not_published');
      } on ApiException catch (e) {
        expect(e.status, 409);
        expect(myProductsErrorKey(e), 'myp.err.not_published');
      }

      final pub = await repo.publish(created.id);
      expect(pub.status, ListingStatus.published);
      expect(pub.publishedAt, isNotNull);
      drafts = await repo.list(status: ListingStatus.draft);
      expect(drafts.items, isEmpty);
      expect((await repo.list(status: ListingStatus.published)).total, 1);

      final updated = await repo.update(
        created.id,
        const ProductDraft(title: 'New title', category: 'lighting', priceMin: '1', priceMax: '2'),
      );
      expect(updated.title, 'New title');
      expect(updated.status, ListingStatus.published);

      expect((await repo.unpublish(created.id)).status, ListingStatus.draft);
      await repo.delete(created.id);
      expect((await repo.list()).items, isEmpty);
      try {
        await repo.get(created.id);
        fail('expected 404');
      } on ApiException catch (e) {
        expect(e.status, 404);
      }
    });
  });

  group('live repository', () {
    test('list sends status and paging, create posts the body', () async {
      final adapter = _FakeAdapter((o) {
        if (o.method == 'GET') {
          return _json({
            'items': [
              {'id': 'lst_1', 'status': 'draft', 'title': 'T', 'kind': 'product', 'condition': 'new'},
            ],
            'total': 1,
            'page': 2,
            'page_size': 10,
          });
        }
        return _json({'id': 'lst_2', 'status': 'draft', 'title': 'LED Panel'}, 201);
      });
      final repo = MyListingsRepository(_live(adapter));
      final page = await repo.list(status: ListingStatus.draft, page: 2, pageSize: 10);
      expect(page.items.single.id, 'lst_1');
      final get = adapter.calls.single;
      expect(get.path, '/v1/my/listings');
      expect(get.queryParameters, {'status': 'draft', 'page': 2, 'page_size': 10});

      final created = await repo.create(_valid());
      expect(created.id, 'lst_2');
      final post = adapter.calls.last;
      expect(post.method, 'POST');
      expect(post.path, '/v1/my/listings');
      expect((post.data as Map)['price'], {
        'min': {'amount': '2.50', 'currency': 'USD'},
        'max': {'amount': '4', 'currency': 'USD'},
      });
    });

    test('publish/unpublish/delete/put paths; empty publish body re-reads', () async {
      final adapter = _FakeAdapter((o) {
        if (o.method == 'POST' && o.path.endsWith('/publish')) return _json(<String, dynamic>{});
        if (o.method == 'DELETE') return ResponseBody.fromString('', 204);
        return _json({'id': 'lst_9', 'status': 'published', 'title': 'T'});
      });
      final repo = MyListingsRepository(_live(adapter));
      final p = await repo.publish('lst_9');
      expect(p.status, ListingStatus.published);
      expect(adapter.calls.map((c) => '${c.method} ${c.path}').toList(), [
        'POST /v1/my/listings/lst_9/publish',
        'GET /v1/my/listings/lst_9',
      ]);
      await repo.unpublish('lst_9');
      expect(adapter.calls.last.path, '/v1/my/listings/lst_9/unpublish');
      await repo.update('lst_9', _valid());
      expect(adapter.calls.last.method, 'PUT');
      await repo.delete('lst_9');
      expect(adapter.calls.last.method, 'DELETE');
    });

    test('403 supplier_required and 409 listing_cap_reached map to friendly keys', () async {
      final adapter = _FakeAdapter((o) {
        if (o.path.endsWith('/publish')) {
          return _json({
            'error': {'code': 'listing_cap_reached', 'message': 'cap'}
          }, 409);
        }
        return _json({
          'error': {'code': 'supplier_required', 'message': 'no'}
        }, 403);
      });
      final repo = MyListingsRepository(_live(adapter));
      try {
        await repo.list();
        fail('expected 403');
      } on ApiException catch (e) {
        expect(e.status, 403);
        expect(myProductsErrorKey(e), 'myp.err.supplier_required');
      }
      try {
        await repo.publish('lst_1');
        fail('expected 409');
      } on ApiException catch (e) {
        expect(myProductsErrorKey(e), 'myp.err.cap_reached');
      }
    });
  });
}
