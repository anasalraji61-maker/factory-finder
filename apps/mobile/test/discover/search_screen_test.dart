import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/discover/data/saved_search.dart';
import 'package:factory_finder/features/discover/data/search_facets.dart';
import 'package:factory_finder/features/discover/screens/search_screen.dart';
import 'package:factory_finder/features/discover/widgets/listing_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

String _ar(String key) => AppStrings.lookup('ar', key);

ListingPage _page(int n, {int? total, bool fromCache = false}) => ListingPage(
      items: mockListings.take(n).toList(),
      total: total ?? n,
      page: 1,
      pageSize: 50,
      fromCache: fromCache,
    );

/// Search repository whose answers the test controls. Each distinct query text
/// gets a Completer, so responses can finish in any order.
class _FakeRepo extends DiscoverRepository {
  _FakeRepo() : super(ApiClient(baseUrl: 'http://fake', isMock: true));

  final List<ListingQuery> calls = <ListingQuery>[];
  final Map<String, Completer<PageResult<Listing>>> pending =
      <String, Completer<PageResult<Listing>>>{};

  @override
  Future<PageResult<Listing>> search(ListingQuery q) {
    calls.add(q);
    if (q.query.isEmpty) return Future.value(_page(0));
    return pending
        .putIfAbsent(q.query, () => Completer<PageResult<Listing>>())
        .future;
  }

  @override
  Future<List<Listing>> trending() async => const <Listing>[];

  void answer(String query, PageResult<Listing> page) =>
      pending[query]!.complete(page);

  void fail(String query, Object error) => pending[query]!.completeError(error);
}

Finder _cards() => find.descendant(
      of: find.byType(SearchScreen),
      matching: find.byType(ListingCard),
    );

Finder _searchField() => find.descendant(
      of: find.byType(AppBar),
      matching: find.byType(TextField),
    );

Future<_FakeRepo> _open(WidgetTester tester, {String q = ''}) async {
  final repo = _FakeRepo();
  await pumpApp(
    tester,
    location: '/discover/search${q.isEmpty ? '' : '?q=$q'}',
    logicalSize: const Size(540, 2400),
    overrides: [discoverRepositoryProvider.overrideWithValue(repo)],
  );
  return repo;
}

class _CaptureAdapter implements HttpClientAdapter {
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
        'items': <Object?>[],
        'total': 0,
        'page': 1,
        'page_size': 50,
        'sources': <Object?>[],
      }),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  setUpWidgetTests();

  group('price filter model', () {
    test('counts, equality and copyWith keep the price bounds', () {
      const a = ListingQuery(query: 'x', minPrice: 1, maxPrice: 9);
      expect(a.activeFilterCount, 2);
      expect(a, const ListingQuery(query: 'x', minPrice: 1, maxPrice: 9));
      expect(a == const ListingQuery(query: 'x', minPrice: 1), isFalse);
      expect(a.hashCode, const ListingQuery(query: 'x', minPrice: 1, maxPrice: 9).hashCode);
      final b = a.copyWith(query: 'y', sort: SortOption.trust);
      expect(b.minPrice, 1);
      expect(b.maxPrice, 9);
    });

    test('parsePriceInput and priceParam', () {
      expect(parsePriceInput(''), isNull);
      expect(parsePriceInput('abc'), isNull);
      expect(parsePriceInput('-3'), isNull);
      expect(parsePriceInput(' 12,5 '), 12.5);
      expect(parsePriceInput('0'), 0);
      expect(priceParam(10), '10');
      expect(priceParam(10.5), '10.5');
    });

    test('mock catalogue filters by unit price overlap', () {
      final all = filterMockListings(const ListingQuery()).items;
      final cheap = filterMockListings(const ListingQuery(maxPrice: 5)).items;
      expect(cheap, isNotEmpty);
      expect(cheap.length, lessThan(all.length));
      for (final l in cheap) {
        expect(l.price.min.value <= 5, isTrue);
      }
      final dear = filterMockListings(const ListingQuery(minPrice: 100000)).items;
      for (final l in dear) {
        expect(l.price.max.value >= 100000, isTrue);
      }
      expect(
        filterMockListings(const ListingQuery(minPrice: 10, maxPrice: 5)).items,
        isEmpty,
      );
    });

    test('saved search payload carries price bounds', () {
      final p = savedSearchPayload(const ListingQuery(query: 'led', minPrice: 2, maxPrice: 7.5));
      expect(p['min_price'], '2');
      expect(p['max_price'], '7.5');
      expect(canSaveSearch(const ListingQuery(minPrice: 1)), isTrue);
    });

    test('live search sends min_price and max_price', () async {
      final adapter = _CaptureAdapter();
      final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = adapter;
      final repo = DiscoverRepository(
        ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio),
        cache: ReadCache(MemoryStore()),
      );
      await repo.search(const ListingQuery(
        query: 'led',
        condition: ItemCondition.used,
        maxMoq: 100,
        minPrice: 3,
        maxPrice: 9.5,
      ));
      expect(adapter.calls, hasLength(1));
      final qp = adapter.calls.single.queryParameters;
      expect(qp['min_price'], '3');
      expect(qp['max_price'], '9.5');
      expect(qp['moq_max'], 100);
      expect(qp['condition'], 'used');
      expect(qp['q'], 'led');
    });
  });

  testWidgets('search: debounced typing; an older response never overwrites a newer one',
      (tester) async {
    final repo = await _open(tester);
    expect(repo.calls.where((c) => c.query.isNotEmpty), isEmpty);

    await tester.enterText(_searchField(), 'a');
    await tester.pump(const Duration(milliseconds: 100));
    // Still inside the debounce window: no request yet.
    expect(repo.calls.where((c) => c.query.isNotEmpty), isEmpty);
    await tester.pump(const Duration(milliseconds: 500));
    expect(repo.calls.where((c) => c.query == 'a'), isNotEmpty);

    await tester.enterText(_searchField(), 'ab');
    await tester.pump(const Duration(milliseconds: 600));
    expect(repo.calls.where((c) => c.query == 'ab'), isNotEmpty);

    // Newer request ('ab') finishes first, the older one ('a') afterwards.
    repo.answer('ab', _page(2));
    await settle(tester, frames: 4);
    expect(_cards(), findsNWidgets(2));
    repo.answer('a', _page(1));
    await settle(tester, frames: 4);
    expect(_cards(), findsNWidgets(2));

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('search: error shows retry that refetches and recovers', (tester) async {
    final repo = await _open(tester, q: 'zzz');
    expect(repo.pending.containsKey('zzz'), isTrue);
    repo.fail('zzz', ApiException(status: 500, code: 'server_error', message: 'boom'));
    await settle(tester, frames: 4);

    final errorState = find.descendant(
      of: find.byType(SearchScreen),
      matching: find.byType(ErrorState),
    );
    expect(errorState, findsOneWidget);
    final retry = find.descendant(of: errorState, matching: find.text(_ar('common.retry')));
    expect(retry, findsOneWidget);

    // The retry must hit the repository again (fresh completer).
    final before = repo.calls.where((c) => c.query == 'zzz').length;
    repo.pending.remove('zzz');
    await tester.tap(retry);
    await settle(tester, frames: 3);
    expect(repo.calls.where((c) => c.query == 'zzz').length, greaterThan(before));
    repo.answer('zzz', _page(1));
    await settle(tester, frames: 4);
    expect(_cards(), findsOneWidget);
    expect(errorState, findsNothing);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('search: empty result, saved-copy banner and truncation note', (tester) async {
    final repo = await _open(tester, q: 'nothing');
    repo.answer('nothing', _page(0));
    await settle(tester, frames: 4);
    expect(
      find.descendant(
        of: find.byType(SearchScreen),
        matching: find.text(_ar('discover.empty_title')),
      ),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('search-truncated')), findsNothing);

    await tester.enterText(_searchField(), 'bulk');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pump();
    expect(repo.pending.containsKey('bulk'), isTrue);
    repo.answer('bulk', _page(2, total: 120, fromCache: true));
    await settle(tester, frames: 4);
    expect(_cards(), findsNWidgets(2));
    expect(find.byKey(const ValueKey('offline-banner')), findsOneWidget);
    expect(find.byKey(const ValueKey('search-truncated')), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('search: applying filters keeps typed text and parses price bounds',
      (tester) async {
    final repo = await _open(tester);
    await tester.enterText(_searchField(), 'steel');
    await tester.tap(find.byTooltip(_ar('discover.filters')));
    await settle(tester, frames: 6);

    final minField = find.byKey(const ValueKey('filter-min-price'));
    final maxField = find.byKey(const ValueKey('filter-max-price'));
    expect(minField, findsOneWidget);
    // Bounds typed the wrong way round are swapped.
    await tester.enterText(minField, '9');
    await tester.enterText(maxField, '2.5');
    await tester.tap(find.text(_ar('common.apply')));
    await settle(tester, frames: 6);

    final last = repo.calls.last;
    expect(last.query, 'steel');
    expect(last.minPrice, 2.5);
    expect(last.maxPrice, 9);
    expect(last.activeFilterCount, 2);

    // Reopening shows the persisted bounds; Reset clears them.
    await tester.tap(find.byTooltip(_ar('discover.filters')));
    await settle(tester, frames: 6);
    expect(
      tester.widget<TextField>(find.byKey(const ValueKey('filter-min-price'))).controller!.text,
      '2.5',
    );
    await tester.tap(find.text(_ar('common.reset')));
    await settle(tester, frames: 6);
    expect(repo.calls.last.query, 'steel');
    expect(repo.calls.last.minPrice, isNull);
    expect(repo.calls.last.activeFilterCount, 0);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
