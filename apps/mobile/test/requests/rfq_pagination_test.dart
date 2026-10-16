import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:flutter_test/flutter_test.dart';

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

void main() {
  group('mock pagination', () {
    final repo = RfqRepository(ApiClient(baseUrl: 'http://fake', isMock: true));
    const filter = RfqFilter(mine: true);

    test('without cursor returns everything with no next_cursor', () async {
      final page = await repo.list(filter);
      expect(page.nextCursor, isNull);
      expect(page.hasMore, isFalse);
      expect(page.items.length, page.total);
    });

    test('small page returns next_cursor and the cursor continues', () async {
      final all = (await repo.list(filter)).items;
      expect(all.length, greaterThan(1));
      final first = await repo.list(filter, pageSize: 1);
      expect(first.items.map((r) => r.id), [all.first.id]);
      expect(first.hasMore, isTrue);
      final seen = [...first.items];
      var cursor = first.nextCursor;
      while (cursor != null) {
        final next = await repo.list(filter, cursor: cursor, pageSize: 1);
        seen.addAll(next.items);
        cursor = next.nextCursor;
      }
      expect(seen.map((r) => r.id), all.map((r) => r.id));
    });

    test('malformed cursor -> 422 invalid_cursor', () async {
      expect(
        repo.list(filter, cursor: 'garbage'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid_cursor')),
      );
    });
  });

  group('live pagination', () {
    final item = buildMockRequests().first.toJson();

    test('no cursor: param omitted, next_cursor null', () async {
      final a = _Adapter({'items': [item], 'total': 1, 'page': 1, 'page_size': 50});
      final page = await RfqRepository(_live(a)).list(const RfqFilter(mine: false));
      expect(a.calls.single.queryParameters.containsKey('cursor'), isFalse);
      expect(page.nextCursor, isNull);
      expect(page.items.length, 1);
    });

    test('cursor is sent and next_cursor parsed', () async {
      final a = _Adapter({
        'items': [item],
        'total': 5,
        'page': 1,
        'page_size': 1,
        'next_cursor': 'abc123',
      });
      final page = await RfqRepository(_live(a))
          .list(const RfqFilter(mine: false), cursor: 'prev', pageSize: 1);
      final q = a.calls.single.queryParameters;
      expect(q['cursor'], 'prev');
      expect(q['page_size'], 1);
      expect(page.nextCursor, 'abc123');
      expect(page.hasMore, isTrue);
    });
  });
}
