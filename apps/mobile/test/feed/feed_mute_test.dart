import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Rec implements HttpClientAdapter {
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    final muted = options.method == 'PUT';
    return ResponseBody.fromString(
      jsonEncode(<String, Object?>{'supplier_id': 'sup_cn_001', 'muted': muted}),
      200,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _FailingMute extends MockFeedRepository {
  Object? error;
  final Completer<void> gate = Completer<void>();
  bool useGate = false;

  @override
  Future<MuteState> muteSupplier(String supplierId) async {
    if (useGate) await gate.future;
    if (error != null) throw error!;
    return super.muteSupplier(supplierId);
  }
}

ProviderContainer _container(FeedRepository repo) {
  final c = ProviderContainer(overrides: <Override>[
    keyValueStoreProvider.overrideWithValue(MemoryStore()),
    secureStoreProvider.overrideWithValue(MemoryStore()),
    feedRepositoryProvider.overrideWithValue(repo),
  ]);
  addTearDown(c.dispose);
  return c;
}

void main() {
  test('live repository uses PUT and DELETE on /v1/feed/mutes/{id}', () async {
    final rec = _Rec();
    final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = rec;
    final repo = LiveFeedRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
    final on = await repo.muteSupplier('sup_cn_001');
    expect(rec.calls.last.method, 'PUT');
    expect(rec.calls.last.path, '/v1/feed/mutes/sup_cn_001');
    expect(on.muted, isTrue);
    final off = await repo.unmuteSupplier('sup_cn_001');
    expect(rec.calls.last.method, 'DELETE');
    expect(off.muted, isFalse);
  });

  group('mock repository', () {
    test('hides muted suppliers from every list and brings them back', () async {
      final repo = MockFeedRepository();
      Future<Set<String>> homeSuppliers() async =>
          (await repo.home(limit: 50)).items.map((p) => p.supplierId).toSet();
      expect(await homeSuppliers(), contains('sup_cn_001'));
      expect((await repo.muteSupplier('sup_cn_001')).muted, isTrue);
      expect(await homeSuppliers(), isNot(contains('sup_cn_001')));
      expect((await repo.trending(limit: 50)).items.any((p) => p.supplierId == 'sup_cn_001'), isFalse);
      expect((await repo.supplierPosts('sup_cn_001')).items, isEmpty);
      expect((await repo.unmuteSupplier('sup_cn_001')).muted, isFalse);
      expect(await homeSuppliers(), contains('sup_cn_001'));
    });

    test('muting your own supplier is rejected', () async {
      final repo = MockFeedRepository(supplierId: () => 'sup_cn_002');
      expect(
        repo.muteSupplier('sup_cn_002'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'cannot_mute_self')),
      );
    });
  });

  group('FeedActions.toggleMute', () {
    test('is optimistic, then confirmed', () async {
      final repo = _FailingMute()..useGate = true;
      final c = _container(repo);
      final f = c.read(feedActionsProvider).toggleMute('sup_cn_001');
      expect(c.read(mutedSuppliersProvider), contains('sup_cn_001'));
      // A second tap while in flight is ignored.
      await c.read(feedActionsProvider).toggleMute('sup_cn_001');
      expect(c.read(mutedSuppliersProvider), contains('sup_cn_001'));
      repo.gate.complete();
      await f;
      expect(c.read(mutedSuppliersProvider), contains('sup_cn_001'));
      await c.read(feedActionsProvider).toggleMute('sup_cn_001');
      expect(c.read(mutedSuppliersProvider), isEmpty);
    });

    test('rolls back and rethrows on error', () async {
      final repo = _FailingMute()
        ..error = ApiException(status: 500, code: 'http_500', message: 'x');
      final c = _container(repo);
      await expectLater(c.read(feedActionsProvider).toggleMute('sup_cn_001'), throwsA(isA<ApiException>()));
      expect(c.read(mutedSuppliersProvider), isEmpty);
    });
  });
}
