import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/reco/chart_math.dart';
import 'package:factory_finder/features/reco/recently_viewed.dart';
import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:factory_finder/features/reco/reco_repository.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

Map<String, dynamic> _obj(String name) =>
    Map<String, dynamic>.from(_load(name) as Map);

class _Adapter implements HttpClientAdapter {
  _Adapter(this.body);

  final Object body;
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return ResponseBody.fromString(
      jsonEncode(body),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

ApiClient _client(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

PricePoint _pt(int dayOffset, String avg) => PricePoint(
      t: DateTime.utc(2026, 1, 1).add(Duration(days: dayOffset)),
      avg: avg,
      min: avg,
      max: avg,
    );

void main() {
  group('parsing', () {
    test('price history fixture', () {
      final h = PriceHistory.fromJson(_obj('price_history'));
      expect(h.listingId, 'lst_0041');
      expect(h.currency, 'USD');
      expect(h.bucket, PriceBucket.week);
      expect(h.synthetic, isFalse);
      expect(h.points, hasLength(12));
      expect(h.points.first.t, DateTime.utc(2026, 7, 17));
      expect(h.points.first.avg, '3.20');
      expect(h.summary?.min, '2.85');
      expect(h.summary?.observations, 22);
      expect(h.trend.direction, PriceDirection.down);
      expect(h.trend.changePct, '-9.38');
      expect(h.trend.insufficientData, isFalse);
      expect(h.hints?.suggestedTarget.amount, '2.76');
      expect(h.hints?.suggestedTarget.currency, 'USD');
      expect(h.hints?.atPeriodLow, isFalse);
      expect(h.hasEnoughData, isTrue);
    });

    test('insufficient data: no hints, no change_pct, flagged synthetic', () {
      final h = PriceHistory.fromJson(_obj('price_history_insufficient'));
      expect(h.synthetic, isTrue);
      expect(h.hints, isNull);
      expect(h.trend.changePct, isNull);
      expect(h.trend.insufficientData, isTrue);
      expect(h.hasEnoughData, isFalse);
    });

    test('missing currency falls back to IQD and bad points are skipped', () {
      final h = PriceHistory.fromJson({
        'listing_id': 'x',
        'points': [
          {'t': 'not a date', 'avg': '1', 'min': '1', 'max': '1', 'n': 1},
          {'t': '2026-01-01T00:00:00Z', 'avg': '5', 'min': '4', 'max': '6', 'n': 2},
        ],
        'trend': {'direction': 'sideways', 'insufficient_data': false},
      });
      expect(h.currency, 'IQD');
      expect(h.points, hasLength(1));
      expect(h.trend.direction, PriceDirection.flat);
      expect(h.hasEnoughData, isFalse); // one point is never enough
    });

    test('similar and recommendations fixtures, reasons by language', () {
      final s = RecoPage.fromJson(_obj('similar'));
      expect(s.listingId, 'lst_0041');
      expect(s.items, hasLength(2));
      expect(s.items.first.listing.id, 'lst_0042');
      expect(s.items.first.reasons.map((r) => r.code),
          ['same_category', 'different_supplier', 'trusted_supplier']);
      expect(s.items.first.reasons.first.text('ar'), 'نفس الفئة');
      expect(s.items.first.reasons.first.text('en'), 'Same category');
      expect(s.items.last.reasons, isEmpty);

      final r = RecoPage.fromJson(_obj('recommendations'));
      expect(r.basedOn, ['lst_0041']);
      expect(r.items.first.reasons.first.refListingId, 'lst_0041');
    });

    test('warning field parses; only partial_results counts as partial', () {
      expect(RecoPage.fromJson(_obj('similar')).warning, isNull);
      final j = _obj('similar')..['warning'] = 'partial_results: budget';
      final p = RecoPage.fromJson(j);
      expect(p.warning, 'partial_results: budget');
      expect(p.isPartial, isTrue);
      expect(RecoPage.fromJson(_obj('similar')..['warning'] = 'other').isPartial, isFalse);
    });

    test('reason text falls back to the other language, then the code', () {
      const onlyEn = RecoReason(code: 'c', en: 'English', ar: '');
      expect(onlyEn.text('ar'), 'English');
      const none = RecoReason(code: 'c', en: '', ar: '');
      expect(none.text('en'), 'c');
    });
  });

  group('chart point mapping', () {
    test('x follows time, y is inverted price, padding respected', () {
      final pts = [_pt(0, '10'), _pt(1, '20'), _pt(2, '15')];
      final o = mapChartPoints(pts, const Size(100, 60), padding: EdgeInsets.zero);
      expect(o[0], const Offset(0, 60));
      expect(o[1], const Offset(50, 0));
      expect(o[2], const Offset(100, 30));

      final padded = mapChartPoints(pts, const Size(120, 80),
          padding: const EdgeInsets.fromLTRB(10, 10, 10, 10));
      expect(padded[0], const Offset(10, 70));
      expect(padded[1], const Offset(60, 10));
      expect(padded[2], const Offset(110, 40));
    });

    test('uneven timestamps are proportional', () {
      final pts = [_pt(0, '1'), _pt(1, '2'), _pt(4, '3')];
      final o = mapChartPoints(pts, const Size(100, 10), padding: EdgeInsets.zero);
      expect(o.map((e) => e.dx), [0, 25, 100]);
    });

    test('single point is centred, flat series sits in the middle', () {
      final one = mapChartPoints([_pt(0, '7')], const Size(100, 40), padding: EdgeInsets.zero);
      expect(one.single, const Offset(50, 20));
      final flat = mapChartPoints([_pt(0, '7'), _pt(1, '7')], const Size(100, 40),
          padding: EdgeInsets.zero);
      expect(flat.map((e) => e.dy), [20, 20]);
    });

    test('identical timestamps are spread evenly; empty gives empty', () {
      final pts = [_pt(0, '1'), _pt(0, '2'), _pt(0, '3')];
      final o = mapChartPoints(pts, const Size(100, 10), padding: EdgeInsets.zero);
      expect(o.map((e) => e.dx), [0, 50, 100]);
      expect(mapChartPoints(const [], const Size(10, 10)), isEmpty);
    });

    test('bucket choice and date label', () {
      expect(bucketForDays(30), PriceBucket.day);
      expect(bucketForDays(90), PriceBucket.day);
      expect(bucketForDays(365), PriceBucket.week);
      expect(formatChartDate(DateTime.utc(2026, 3, 5)), '2026-03-05');
    });
  });

  group('live repository (fake Dio)', () {
    test('price history query and parsing', () async {
      final a = _Adapter(_load('price_history') as Object);
      final repo = LiveRecoRepository(_client(a));
      final h = await repo.priceHistory('lst_0041', days: 365);
      expect(a.calls.single.path, '/v1/listings/lst_0041/price-history');
      expect(a.calls.single.queryParameters, {'days': 365, 'bucket': 'week'});
      expect(h.points, hasLength(12));
    });

    test('similar query', () async {
      final a = _Adapter(_load('similar') as Object);
      final page = await LiveRecoRepository(_client(a)).similar('lst_0041', limit: 5);
      expect(a.calls.single.path, '/v1/listings/lst_0041/similar');
      expect(a.calls.single.queryParameters, {'limit': 5});
      expect(page.items, hasLength(2));
    });

    test('recommendations send ref (capped at 20), country upper-cased', () async {
      final a = _Adapter(_load('recommendations') as Object);
      final repo = LiveRecoRepository(_client(a));
      final refs = [for (var i = 0; i < 25; i++) 'lst_$i'];
      await repo.recommendations(refs: refs, country: 'cn', limit: 8);
      final q = a.calls.single.queryParameters;
      expect(a.calls.single.path, '/v1/recommendations');
      expect((q['ref'] as String).split(','), hasLength(20));
      expect(q['ref'], startsWith('lst_0,lst_1,'));
      expect(q['country'], 'CN');
      expect(q['limit'], 8);
    });

    test('no refs and no country: neither parameter is sent', () async {
      final a = _Adapter(_load('recommendations') as Object);
      await LiveRecoRepository(_client(a)).recommendations();
      expect(a.calls.single.queryParameters.containsKey('ref'), isFalse);
      expect(a.calls.single.queryParameters.containsKey('country'), isFalse);
    });
  });

  group('mock repository', () {
    final repo = MockRecoRepository(clock: () => DateTime.utc(2026, 10, 15, 8));

    test('price history is deterministic, synthetic and consistent', () async {
      final a = await repo.priceHistory('lst_001', days: 90);
      final b = await repo.priceHistory('lst_001', days: 90);
      expect(a.points.map((p) => p.avg), b.points.map((p) => p.avg));
      expect(a.synthetic, isTrue);
      expect(a.points, hasLength(90));
      expect(a.points.last.t, DateTime.utc(2026, 10, 15));
      expect(a.hasEnoughData, isTrue);
      final lo = double.parse(a.summary!.min);
      final hi = double.parse(a.summary!.max);
      final cur = double.parse(a.summary!.current);
      expect(lo <= cur && cur <= hi, isTrue);
      expect(double.parse(a.hints!.suggestedTarget.amount), lessThan(cur + 0.0001));
      expect(a.hints!.suggestedTarget.currency, a.currency);
      final year = await repo.priceHistory('lst_001', days: 365);
      expect(year.bucket, PriceBucket.week);
      expect(year.points, hasLength(53));
    });

    test('unknown listing is a 404', () async {
      expect(
        repo.priceHistory('nope'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)),
      );
    });

    test('similar excludes the listing, keeps the kind, gives reasons', () async {
      final page = await repo.similar('lst_001', limit: 4);
      expect(page.items, hasLength(4));
      expect(page.items.any((i) => i.listing.id == 'lst_001'), isFalse);
      expect(page.items.first.listing.category, 'electronics');
      expect(page.items.first.reasons, isNotEmpty);
      expect(page.items.first.reasons.first.ar, isNotEmpty);
    });

    test('recommendations: top trusted without refs', () async {
      final page = await repo.recommendations();
      expect(page.basedOn, isEmpty);
      expect(page.items.every((i) => i.reasons.single.code == 'top_trusted'), isTrue);
      final perSupplier = <String, int>{};
      for (final i in page.items) {
        perSupplier[i.listing.supplier.id] = (perSupplier[i.listing.supplier.id] ?? 0) + 1;
      }
      expect(perSupplier.values.every((n) => n <= 3), isTrue);
    });

    test('recommendations follow viewed categories and skip viewed ids', () async {
      final page = await repo.recommendations(refs: ['lst_001', 'unknown_id']);
      expect(page.basedOn, ['lst_001']);
      expect(page.items.any((i) => i.listing.id == 'lst_001'), isFalse);
      expect(page.items, isNotEmpty);
      expect(page.items.every((i) => i.listing.category == 'electronics'), isTrue);
      expect(page.items.first.reasons.single.code, 'because_viewed');
      expect(page.items.first.reasons.single.refListingId, 'lst_001');
    });
  });

  group('recently viewed store', () {
    test('pushRecent: most recent first, deduped, capped', () {
      expect(pushRecent(['a', 'b', 'c'], 'b'), ['b', 'a', 'c']);
      expect(pushRecent(const [], '  '), isEmpty);
      final many = [for (var i = 0; i < 20; i++) 'id$i'];
      final next = pushRecent(many, 'new');
      expect(next, hasLength(kRecentlyViewedCap));
      expect(next.first, 'new');
      expect(next.contains('id19'), isFalse);
    });

    test('decodeRecent is tolerant', () {
      expect(decodeRecent(null), isEmpty);
      expect(decodeRecent('{bad json'), isEmpty);
      expect(decodeRecent('{"a":1}'), isEmpty);
      expect(decodeRecent('["a", 3, "", "a", " b "]'), ['a', 'b']);
    });

    ProviderContainer container(MemoryStore store) {
      final c = ProviderContainer(overrides: [keyValueStoreProvider.overrideWithValue(store)]);
      addTearDown(c.dispose);
      return c;
    }

    test('loads stored ids, persists additions, clears', () async {
      final store = MemoryStore({kRecentlyViewedKey: '["x","y"]'});
      final c = container(store);
      final n = c.read(recentlyViewedProvider.notifier);
      expect(c.read(recentlyViewedProvider).loaded, isFalse);
      await n.ready;
      expect(c.read(recentlyViewedProvider).ids, ['x', 'y']);
      expect(c.read(recentlyViewedProvider).loaded, isTrue);

      await n.add('z');
      await n.add('x');
      expect(c.read(recentlyViewedProvider).ids, ['x', 'z', 'y']);
      expect(jsonDecode(store.data[kRecentlyViewedKey]!), ['x', 'z', 'y']);

      await n.clear();
      expect(c.read(recentlyViewedProvider).ids, isEmpty);
      expect(store.data.containsKey(kRecentlyViewedKey), isFalse);
    });

    test('an add before the load finished does not drop stored ids', () async {
      final store = MemoryStore({kRecentlyViewedKey: '["x"]'});
      final c = container(store);
      final n = c.read(recentlyViewedProvider.notifier);
      await n.add('new'); // awaits the load first
      expect(c.read(recentlyViewedProvider).ids, ['new', 'x']);
      expect(jsonDecode(store.data[kRecentlyViewedKey]!), ['new', 'x']);
    });

    test('adding the current first id again does not rewrite', () async {
      final store = MemoryStore();
      final c = container(store);
      final n = c.read(recentlyViewedProvider.notifier);
      await n.add('a');
      store.data.remove(kRecentlyViewedKey);
      await n.add('a');
      expect(store.data.containsKey(kRecentlyViewedKey), isFalse);
    });

    test('a failing store never throws', () async {
      final c = ProviderContainer(overrides: [
        keyValueStoreProvider.overrideWithValue(_BrokenStore()),
      ]);
      addTearDown(c.dispose);
      final n = c.read(recentlyViewedProvider.notifier);
      await n.add('a');
      expect(c.read(recentlyViewedProvider).ids, ['a']);
      await n.clear();
      expect(c.read(recentlyViewedProvider).ids, isEmpty);
    });
  });
}

class _BrokenStore implements KeyValueStore {
  @override
  Future<String?> get(String key) async => throw StateError('no storage');

  @override
  Future<void> remove(String key) async => throw StateError('no storage');

  @override
  Future<void> set(String key, String value) async => throw StateError('no storage');
}
