import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

ApiException _api(int status, String code) =>
    ApiException(status: status, code: code, message: code);

FeedPost _post(String id) => FeedPost(id: id, supplierId: 'sup_x', body: 'b $id');

FeedPage<FeedPost> _page(List<String> ids, String? next) => FeedPage<FeedPost>(
      items: <FeedPost>[for (final i in ids) _post(i)],
      nextCursor: next,
    );

class _Recorder implements HttpClientAdapter {
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
        'next_cursor': 'snap.v1:abc==/+?&x=1',
        'source': 'trending',
      }),
      200,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _FailingLike extends MockFeedRepository {
  Object? error;

  @override
  Future<LikeState> like(String postId) async {
    if (error != null) throw error!;
    return super.like(postId);
  }

  @override
  Future<void> reportPost(String postId, ReportReason reason, {String? details}) async {
    if (error != null) throw error!;
    return super.reportPost(postId, reason, details: details);
  }
}

class _SlowFollowing extends MockFeedRepository {
  _SlowFollowing() : super(initialFollows: <String>{});

  final Completer<void> gate = Completer<void>();

  @override
  Future<FeedPage<FollowedSupplier>> following({String? cursor, int limit = 50}) async {
    final page = await super.following(cursor: cursor, limit: limit);
    await gate.future; // the list was read before the tap, delivered after
    return page;
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

Future<void> _tick() async {
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
}

void main() {
  group('opaque snapshot cursor', () {
    test('is parsed and sent back byte for byte', () async {
      const snap = 'snap.v1:abc==/+?&x=1 é';
      final page = FeedPage.parse(
        <String, Object?>{'items': <Object?>[], 'next_cursor': snap, 'source': 'trending'},
        FeedPost.fromJson,
      );
      expect(page.nextCursor, snap);
      expect(page.hasMore, isTrue);

      final rec = _Recorder();
      final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = rec;
      final repo = LiveFeedRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
      final first = await repo.trending();
      expect(rec.calls.single.queryParameters.containsKey('cursor'), isFalse);
      await repo.trending(cursor: first.nextCursor);
      expect(rec.calls.last.queryParameters['cursor'], 'snap.v1:abc==/+?&x=1');
    });

    test('null, empty or non-string cursors mean the end', () {
      for (final c in <Object?>[null, '', 5, <Object?>[]]) {
        final p = FeedPage.parse(<String, Object?>{'items': <Object?>[], 'next_cursor': c},
            FeedPost.fromJson);
        expect(p.nextCursor, isNull);
        expect(p.hasMore, isFalse);
      }
    });
  });

  group('list pagination', () {
    test('stops at the end and never fetches again', () async {
      final cursors = <String?>[];
      final ctrl = FeedListController(PostStore(), (c) async {
        cursors.add(c);
        return c == null ? _page(<String>['a', 'b'], 'c1') : _page(<String>['b', 'c'], null);
      });
      addTearDown(ctrl.dispose);
      await _tick();
      await ctrl.loadMore();
      expect(ctrl.state.ids, <String>['a', 'b', 'c']);
      expect(ctrl.state.hasMore, isFalse);
      await ctrl.loadMore();
      await ctrl.loadMore();
      expect(cursors, <String?>[null, 'c1']);
    });

    test('a repeated cursor ends the list instead of looping', () async {
      final ctrl = FeedListController(PostStore(), (c) async => _page(<String>['a'], 'same'));
      addTearDown(ctrl.dispose);
      await _tick();
      expect(ctrl.state.nextCursor, 'same');
      await ctrl.loadMore();
      expect(ctrl.state.hasMore, isFalse);
    });

    test('invalid_cursor on load more restarts from the first page', () async {
      var snapshot = 1;
      final cursors = <String?>[];
      final ctrl = FeedListController(PostStore(), (c) async {
        cursors.add(c);
        if (c == null) return _page(<String>['n$snapshot'], 'snap$snapshot');
        throw _api(422, 'invalid_cursor');
      });
      addTearDown(ctrl.dispose);
      await _tick();
      await ctrl.loadMore();
      expect((ctrl.state.moreError as ApiException).code, 'invalid_cursor');
      expect(ctrl.state.ids, <String>['n1']);
      snapshot = 2;
      await ctrl.loadMore(); // retry = refresh, never the dead cursor again
      expect(cursors, <String?>[null, 'snap1', null]);
      expect(ctrl.state.ids, <String>['n2']);
      expect(ctrl.state.nextCursor, 'snap2');
      expect(ctrl.state.moreError, isNull);
    });

    test('refresh resets the cursor and drops an in-flight load more', () async {
      final pending = Completer<FeedPage<FeedPost>>();
      var firstCalls = 0;
      final ctrl = FeedListController(PostStore(), (c) {
        if (c == null) {
          firstCalls++;
          return Future<FeedPage<FeedPost>>.value(_page(<String>['a'], 'c$firstCalls'));
        }
        return pending.future;
      });
      addTearDown(ctrl.dispose);
      await _tick();
      final more = ctrl.loadMore();
      expect(ctrl.state.loadingMore, isTrue);
      await ctrl.refresh();
      expect(ctrl.state.loadingMore, isFalse);
      expect(ctrl.state.nextCursor, 'c2');
      pending.complete(_page(<String>['zzz'], 'late'));
      await more;
      expect(ctrl.state.ids, <String>['a']);
      expect(ctrl.state.nextCursor, 'c2');
    });

    test('a failed refresh keeps the shown posts and the old cursor', () async {
      var fail = false;
      final ctrl = FeedListController(PostStore(), (c) async {
        if (fail) throw _api(500, 'http_500');
        return _page(<String>['a'], 'c1');
      });
      addTearDown(ctrl.dispose);
      await _tick();
      fail = true;
      await ctrl.refresh();
      expect(ctrl.state.ids, <String>['a']);
      expect(ctrl.state.error, isNotNull);
      expect(ctrl.state.nextCursor, 'c1');
      expect(ctrl.state.loading, isFalse);
    });
  });

  group('like / hidden posts', () {
    test('404 on like removes the post instead of restoring it', () async {
      final repo = _FailingLike();
      final c = _container(repo);
      final p = (await repo.trending()).items.first;
      c.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[p]);
      repo.error = _api(404, 'not_found');
      await expectLater(
        c.read(feedActionsProvider).toggleLike(p.id),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)),
      );
      expect(c.read(feedPostStoreProvider).containsKey(p.id), isFalse);
      // A later tap on the vanished post is a no-op.
      await c.read(feedActionsProvider).toggleLike(p.id);
    });

    test('other failures still roll back', () async {
      final repo = _FailingLike();
      final c = _container(repo);
      final p = (await repo.trending()).items.first;
      c.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[p]);
      repo.error = _api(500, 'http_500');
      await expectLater(c.read(feedActionsProvider).toggleLike(p.id), throwsA(isA<ApiException>()));
      final cur = c.read(feedPostStoreProvider)[p.id]!;
      expect(cur.viewerLiked, p.viewerLiked);
      expect(cur.likeCount, p.likeCount);
    });

    test('report on a hidden post removes it; other errors keep it', () async {
      final repo = _FailingLike();
      final c = _container(repo);
      final p = (await repo.trending()).items.first;
      c.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[p]);
      repo.error = _api(429, 'rate_limited');
      await expectLater(
          c.read(feedActionsProvider).reportPost(p.id, ReportReason.spam, null), throwsA(isA<ApiException>()));
      expect(c.read(feedPostStoreProvider).containsKey(p.id), isTrue);
      repo.error = _api(404, 'not_found');
      await expectLater(
          c.read(feedActionsProvider).reportPost(p.id, ReportReason.spam, null), throwsA(isA<ApiException>()));
      expect(c.read(feedPostStoreProvider).containsKey(p.id), isFalse);
    });
  });

  group('following', () {
    test('a follow tapped while the list loads is not overwritten', () async {
      final repo = _SlowFollowing();
      final ctrl = FollowingController(repo);
      addTearDown(ctrl.dispose);
      final toggle = ctrl.toggle('sup_cn_001');
      expect(ctrl.state.isFollowing('sup_cn_001'), isTrue);
      repo.gate.complete();
      await toggle;
      await _tick();
      expect(ctrl.state.loaded, isTrue);
      expect(ctrl.state.isFollowing('sup_cn_001'), isTrue);
    });
  });

  group('composer limits', () {
    test('lengths count characters, not UTF-16 units', () {
      expect(validatePostBody('😀' * 1500), isNull);
      expect(validatePostBody('a' * kPostBodyMax), isNull);
      expect(validatePostBody('a' * (kPostBodyMax + 1)), 'feed.err.post_too_long');
      expect(validateCommentBody('😀' * kCommentBodyMax), isNull);
      expect(validateCommentBody('a' * (kCommentBodyMax + 1)), 'feed.err.comment_too_long');
      expect(validateReportDetails('😀' * kReportDetailsMax), isNull);
      expect(validateReportDetails('a' * (kReportDetailsMax + 1)), 'feed.err.details_too_long');
      expect(validatePostBody('   \n '), 'feed.err.body_empty');
    });

    test('too many tags is detected, duplicates and invalid ones do not count', () {
      expect(hasTooManyTags('a b c d e'), isFalse);
      expect(hasTooManyTags('a b c d e f'), isTrue);
      expect(hasTooManyTags('#a, #A, b c d e'), isFalse);
      expect(hasTooManyTags('a b c d e ${'x' * 31}'), isFalse);
      expect(hasInvalidTags('a b c d e ${'x' * 31}'), isTrue);
      expect(parseTags('a b c d e f g'), hasLength(kPostTagsMax));
    });

    test('mock rejects 6 media, bad media paths and tags with contact details', () async {
      final repo = MockFeedRepository(supplierId: () => 'sup_cn_001');
      String m(int i) => '/v1/media/files/${i.toRadixString(16).padLeft(32, '0')}.jpg';
      await expectLater(
        repo.createPost(PostDraft(body: 'ok', media: <String>[for (var i = 0; i < 6; i++) m(i)])),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'validation_error')),
      );
      await expectLater(
        repo.createPost(const PostDraft(body: 'ok', media: <String>['http://evil.example/x.jpg'])),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid_media')),
      );
      final ok = await repo.createPost(PostDraft(body: 'ok', media: <String>[for (var i = 0; i < 5; i++) m(i)]));
      expect(ok.media, hasLength(5));
    });
  });

  group('report details', () {
    test('long details are cut at 300 characters without splitting an emoji', () async {
      final rec = _Recorder();
      final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = rec;
      final repo = LiveFeedRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
      await repo.reportPost('p1', ReportReason.spam, details: '😀' * 400);
      final body = rec.calls.single.data as Map;
      final details = body['details'] as String;
      expect(details.runes.length, kReportDetailsMax);
      expect(body['reason'], 'spam');
    });
  });

  group('post image urls', () {
    test('relative urls get the base and a width hint, absolute ones stay', () {
      expect(postImageUrl('http://h/', '/v1/media/files/a.jpg', width: 600),
          'http://h/v1/media/files/a.jpg?w=600');
      expect(postImageUrl('http://h', 'v1/media/files/a.jpg'), 'http://h/v1/media/files/a.jpg');
      expect(postImageUrl('http://h', 'https://cdn.x/a.jpg', width: 600), 'https://cdn.x/a.jpg');
    });
  });
}
