import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/discover/data/search_facets.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Replies with [body] while [online]; otherwise fails like a dead socket, or
/// with [offlineStatus] when set.
class _Adapter implements HttpClientAdapter {
  _Adapter(this.body);

  Object? body;
  bool online = true;
  int? offlineStatus;
  int calls = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls++;
    if (!online) {
      if (offlineStatus != null) {
        return ResponseBody.fromString(
          jsonEncode(<String, Object?>{
            'error': <String, Object?>{'code': 'server', 'message': 'x'},
          }),
          offlineStatus!,
          headers: <String, List<String>>{
            Headers.contentTypeHeader: <String>[Headers.jsonContentType],
          },
        );
      }
      throw DioException(
        requestOptions: options,
        type: DioExceptionType.connectionError,
        error: 'offline',
      );
    }
    return ResponseBody.fromString(
      jsonEncode(body),
      200,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

ApiClient _client(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = a;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

void main() {
  group('search offline cache', () {
    Map<String, Object?> searchBody() => <String, Object?>{
          'items': <Object?>[mockListings.first.toJson(), mockListings[1].toJson()],
          'total': 2,
          'page': 1,
          'page_size': 50,
        };

    test('network failure serves the last successful page for the same query', () async {
      final adapter = _Adapter(searchBody());
      final store = MemoryStore();
      final repo = DiscoverRepository(_client(adapter), cache: ReadCache(store));
      const q = ListingQuery(query: 'led');

      final live = await repo.search(q) as ListingPage;
      expect(live.fromCache, isFalse);
      expect(live.items.length, 2);

      adapter.online = false;
      final saved = await repo.search(q) as ListingPage;
      expect(saved.fromCache, isTrue);
      expect(saved.items.map((l) => l.id), live.items.map((l) => l.id));
    });

    test('a different query is not served from another query\'s cache', () async {
      final adapter = _Adapter(searchBody());
      final repo = DiscoverRepository(_client(adapter), cache: ReadCache(MemoryStore()));
      await repo.search(const ListingQuery(query: 'led'));
      adapter.online = false;
      expect(
        () => repo.search(const ListingQuery(query: 'steel')),
        throwsA(isA<ApiException>()),
      );
    });

    test('server errors (with a status) are never masked by the cache', () async {
      final adapter = _Adapter(searchBody());
      final repo = DiscoverRepository(_client(adapter), cache: ReadCache(MemoryStore()));
      const q = ListingQuery(query: 'led');
      await repo.search(q);
      adapter
        ..online = false
        ..offlineStatus = 500;
      expect(() => repo.search(q), throwsA(isA<ApiException>()));
    });

    test('expired cache is ignored and the error surfaces', () async {
      final adapter = _Adapter(searchBody());
      var now = DateTime(2026, 10, 15);
      final repo = DiscoverRepository(
        _client(adapter),
        cache: ReadCache(MemoryStore(), now: () => now),
      );
      const q = ListingQuery(query: 'led');
      await repo.search(q);
      adapter.online = false;
      now = now.add(const Duration(hours: 25));
      expect(() => repo.search(q), throwsA(isA<ApiException>()));
    });

    test('without a cache the network error is rethrown', () async {
      final adapter = _Adapter(searchBody())..online = false;
      final repo = DiscoverRepository(_client(adapter));
      expect(() => repo.search(const ListingQuery()), throwsA(isA<ApiException>()));
    });

    test('only the search slot is written', () async {
      final store = MemoryStore();
      final repo = DiscoverRepository(_client(_Adapter(searchBody())), cache: ReadCache(store));
      await repo.search(const ListingQuery());
      expect(store.data.keys.toList(), <String>[kSearchCacheSlot]);
    });
  });

  group('home feed offline cache', () {
    Map<String, Object?> feedBody() => <String, Object?>{
          'items': <Object?>[
            <String, Object?>{
              'id': 'pst_1',
              'supplier_id': 'sup_1',
              'body': 'hello',
              'viewer_liked': true,
              'like_count': 3,
            },
          ],
          'next_cursor': 'c2',
          'source': 'following',
        };

    LiveFeedRepository repo(_Adapter a, MemoryStore s, {String? user = 'usr_1'}) =>
        LiveFeedRepository(
          _client(a),
          cache: ReadCache(s),
          cacheScope: () => user,
        );

    test('serves the saved first page when offline, without per-viewer state', () async {
      final adapter = _Adapter(feedBody());
      final store = MemoryStore();
      final r = repo(adapter, store);
      final live = await r.home();
      expect(live.fromCache, isFalse);
      expect(live.items.single.viewerLiked, isTrue);

      adapter.online = false;
      final saved = await r.home();
      expect(saved.fromCache, isTrue);
      expect(saved.items.single.id, 'pst_1');
      expect(saved.items.single.viewerLiked, isFalse);
      expect(saved.nextCursor, 'c2');
      expect(store.data[kHomeFeedCacheSlot], isNot(contains('viewer_liked')));
    });

    test('is scoped per user and skipped when signed out', () async {
      final adapter = _Adapter(feedBody());
      final store = MemoryStore();
      await repo(adapter, store).home();
      adapter.online = false;
      await expectLater(repo(adapter, store, user: 'usr_2').home(), throwsA(isA<ApiException>()));
      await expectLater(repo(adapter, store, user: null).home(), throwsA(isA<ApiException>()));

      final guestStore = MemoryStore();
      adapter.online = true;
      await repo(adapter, guestStore, user: null).home();
      expect(guestStore.data, isEmpty);
    });

    test('later pages are neither cached nor served from cache', () async {
      final adapter = _Adapter(feedBody());
      final store = MemoryStore();
      final r = repo(adapter, store);
      await r.home(cursor: 'c2');
      expect(store.data, isEmpty);
      await r.home();
      adapter.online = false;
      expect(() => r.home(cursor: 'c2'), throwsA(isA<ApiException>()));
    });
  });
}
