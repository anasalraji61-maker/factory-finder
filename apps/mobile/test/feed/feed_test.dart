import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:factory_finder/features/feed/screens/composer_screen.dart';
import 'package:factory_finder/features/feed/screens/feed_screen.dart';
import 'package:factory_finder/features/feed/screens/post_detail_screen.dart';
import 'package:factory_finder/features/feed/widgets/follow_button.dart';
import 'package:factory_finder/features/feed/widgets/post_card.dart';
import 'package:factory_finder/features/feed/widgets/report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

class _Reply {
  const _Reply(this.body, [this.status = 200, this.headers = const <String, String>{}]);

  final Object? body;
  final int status;
  final Map<String, String> headers;
}

class _Adapter implements HttpClientAdapter {
  _Adapter(this.respond);

  final _Reply Function(RequestOptions) respond;
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    final r = respond(options);
    return ResponseBody.fromString(
      jsonEncode(r.body),
      r.status,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
        for (final e in r.headers.entries) e.key: <String>[e.value],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

LiveFeedRepository _live(_Adapter a) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = a;
  return LiveFeedRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
}

ApiException _api(int status, String code, {int? retry}) =>
    ApiException(status: status, code: code, message: code, retryAfterSeconds: retry);

/// Mock repo whose like / follow / create can be gated or made to fail.
class _GatedRepo extends MockFeedRepository {
  _GatedRepo({String? Function()? supplierId, int postLimit = 10})
      : super(supplierId: supplierId, postLimit: postLimit);

  Completer<void>? gate;
  Object? failWith;
  int likeCalls = 0;
  int createCalls = 0;
  int pageCap = 50;

  Future<void> _maybeWait() async {
    if (gate != null) await gate!.future;
    if (failWith != null) throw failWith!;
  }

  @override
  Future<LikeState> like(String postId) async {
    likeCalls++;
    await _maybeWait();
    return super.like(postId);
  }

  @override
  Future<LikeState> unlike(String postId) async {
    likeCalls++;
    await _maybeWait();
    return super.unlike(postId);
  }

  @override
  Future<FollowState> follow(String supplierId) async {
    await _maybeWait();
    return super.follow(supplierId);
  }

  @override
  Future<FollowState> unfollow(String supplierId) async {
    await _maybeWait();
    return super.unfollow(supplierId);
  }

  @override
  Future<FeedPost> createPost(PostDraft draft) {
    createCalls++;
    return super.createPost(draft);
  }

  @override
  Future<FeedPage<FeedPost>> trending({String? cursor, int limit = kFeedPageSize}) =>
      super.trending(cursor: cursor, limit: limit > pageCap ? pageCap : limit);
}

class _FixedAuth extends AuthController {
  _FixedAuth(Ref ref, Me? me) : super(ref) {
    state = me;
  }
}

const Me _supplierMe = Me(
  id: 'usr_sup',
  name: 'Supplier',
  supplierId: 'sup_cn_001',
  supplierClaimStatus: 'verified',
);
const Me _buyerMe = Me(id: 'usr_buyer', name: 'Buyer');

List<Override> _overrides(FeedRepository repo, {Me? me}) => <Override>[
      keyValueStoreProvider.overrideWithValue(MemoryStore()),
      secureStoreProvider.overrideWithValue(MemoryStore()),
      feedRepositoryProvider.overrideWithValue(repo),
      if (me != null) authProvider.overrideWith((ref) => _FixedAuth(ref, me)),
    ];

Future<GoRouter> _pump(
  WidgetTester tester,
  Widget home, {
  required List<Override> overrides,
  Size size = const Size(360, 800),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = GoRouter(
    routes: <RouteBase>[
      GoRoute(path: '/', builder: (c, s) => home),
      GoRoute(path: '/feed/post/:id', builder: (c, s) => Text('detail-${s.pathParameters['id']}')),
      GoRoute(path: '/listing/:id', builder: (c, s) => Text('listing-${s.pathParameters['id']}')),
      GoRoute(path: '/supplier/:id', builder: (c, s) => Text('supplier-${s.pathParameters['id']}')),
      GoRoute(path: '/compose', builder: (c, s) => const ComposerScreen()),
      GoRoute(path: '/login', builder: (c, s) => const Text('login-page')),
      GoRoute(path: '/supplier-claim', builder: (c, s) => const Text('claim-page')),
    ],
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: MaterialApp.router(
        routerConfig: router,
        locale: const Locale('ar'),
        supportedLocales: const <Locale>[Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
      ),
    ),
  );
  await settle(tester);
  return router;
}

/// Returns a pending comments page per call so tests can finish them out of order.
class _CommentsRepo extends MockFeedRepository {
  final List<Completer<FeedPage<FeedComment>>> pending =
      <Completer<FeedPage<FeedComment>>>[];

  @override
  Future<FeedPage<FeedComment>> comments(String postId,
      {String? cursor, int limit = kFeedPageSize}) {
    final c = Completer<FeedPage<FeedComment>>();
    pending.add(c);
    return c.future;
  }
}

ProviderContainer _container(FeedRepository repo, {Me? me}) {
  final c = ProviderContainer(overrides: _overrides(repo, me: me));
  addTearDown(c.dispose);
  return c;
}

void main() {
  setUpWidgetTests();

  test('comments refresh ignores a stale overlapping response', () async {
    final repo = _CommentsRepo();
    final ctrl = CommentsController(repo, PostStore(), 'pst_1');
    addTearDown(ctrl.dispose);
    // Constructor already started refresh #1; start #2.
    final second = ctrl.refresh();
    expect(repo.pending.length, 2);
    repo.pending[1].complete(const FeedPage<FeedComment>(
        items: <FeedComment>[], nextCursor: 'fresh'));
    await second;
    expect(ctrl.state.nextCursor, 'fresh');
    // The older request finishes last and must not overwrite the newer one.
    repo.pending[0].complete(const FeedPage<FeedComment>(
        items: <FeedComment>[], nextCursor: 'stale'));
    await Future<void>.delayed(Duration.zero);
    expect(ctrl.state.nextCursor, 'fresh');
  });

  group('parsing (live fixtures)', () {
    test('home page', () {
      final page = FeedPage.parse(_load('feed_home_page'), FeedPost.fromJson);
      expect(page.items, hasLength(2));
      expect(page.source, FeedSource.trending);
      expect(page.hasMore, isTrue);
      final p = page.items.first;
      expect(p.id, 'pst_8f3a1c');
      expect(p.supplierId, 'sup_cn_001');
      expect(p.media, hasLength(1));
      expect(p.listingRef, 'lst_0041');
      expect(p.likeCount, 7);
      expect(p.viewerLiked, isTrue);
      expect(p.createdAt, DateTime.utc(2026, 10, 12, 9, 30));
      expect(page.items.last.listingRef, isNull);
      expect(page.items.last.createdAt!.microsecond, 456);
    });

    test('post, comments, states', () {
      final p = FeedPost.fromJson(_load('feed_post'));
      expect(p.media, hasLength(2));
      expect(p.tags, <String>['led', 'new_stock']);
      final cs = FeedPage.parse(_load('feed_comments_page'), FeedComment.fromJson);
      expect(cs.items, hasLength(2));
      expect(cs.hasMore, isFalse);
      expect(cs.items.first.postId, 'pst_8f3a1c');
      final f = FollowState.fromJson(_load('feed_follow_state'));
      expect(f.following, isTrue);
      expect(f.followerCount, 12);
      final l = LikeState.fromJson(_load('feed_like_state'));
      expect(l.liked, isTrue);
      expect(l.likeCount, 8);
      final fl = FeedPage.parse(_load('feed_following_page'), FollowedSupplier.fromJson);
      expect(fl.items.map((e) => e.supplierId), <String>['sup_cn_001', 'sup_cn_003']);
    });

    test('tolerates junk', () {
      final p = FeedPost.fromJson(<String, dynamic>{'id': 1, 'like_count': -3, 'media': 'x'});
      expect(p.id, '1');
      expect(p.likeCount, 0);
      expect(p.media, isEmpty);
      expect(FeedPage.parse<FeedPost>(null, FeedPost.fromJson).items, isEmpty);
    });
  });

  group('content checks', () {
    test('detects url / email / phone / handle', () {
      expect(findContactDetail('see https://shop.example.com now'), ContactKind.url);
      expect(findContactDetail('www.example.cn'), ContactKind.url);
      expect(findContactDetail('mail me: a.b@example.com'), ContactKind.email);
      expect(findContactDetail('call +86 138 0013 8000'), ContactKind.phone);
      expect(findContactDetail('اتصل ٠٧٧٠١٢٣٤٥٦٧٨'), ContactKind.phone);
      expect(findContactDetail('add me on WhatsApp'), ContactKind.handle);
      expect(findContactDetail('راسلني على واتساب'), ContactKind.handle);
      expect(findContactDetail('@someone_here'), ContactKind.handle);
    });

    test('plain text passes', () {
      expect(findContactDetail('MOQ 500 pieces, price 12.5 USD'), isNull);
      expect(findContactDetail('دفعة جديدة من الأقمشة'), isNull);
      expect(findContactDetail('Model 2024'), isNull);
    });

    test('post / comment validation keys', () {
      expect(validatePostBody('  '), 'feed.err.body_empty');
      expect(validatePostBody('a' * 2001), 'feed.err.post_too_long');
      expect(validatePostBody('a' * 2000), isNull);
      expect(validatePostBody('x\u0007y'), 'feed.err.control_chars');
      expect(validatePostBody('line 1\nline 2'), isNull);
      expect(validatePostBody('call 0770 123 4567'), 'feed.err.contact.phone');
      expect(validateCommentBody('a' * 501), 'feed.err.comment_too_long');
      expect(validateCommentBody('hi a@b.com'), 'feed.err.contact.email');
      expect(validateCommentBody('nice'), isNull);
    });

    test('tags', () {
      expect(parseTags('LED, #solar  led new-stock  a_b'), <String>['led', 'solar', 'new-stock', 'a_b']);
      expect(parseTags('1 2 3 4 5 6 7'), hasLength(5));
      expect(parseTags('مصنع،جملة'), <String>['مصنع', 'جملة']);
      expect(hasInvalidTags('ok bad!tag'), isTrue);
      expect(hasInvalidTags('ok fine'), isFalse);
      expect(parseTags('${'x' * 31} ok'), <String>['ok']);
    });

    test('initials', () {
      expect(initialsOf('Shenzhen Brightway Electronics'), 'SB');
      expect(initialsOf('مصنع النور'), 'ما');
      expect(initialsOf(''), '?');
    });
  });

  group('error mapping', () {
    test('every documented code has a specific key', () {
      const expected = <String, String>{
        'content_rejected': 'feed.err.content_rejected',
        'invalid_media': 'feed.err.invalid_media',
        'invalid_cursor': 'feed.err.invalid_cursor',
        'supplier_required': 'feed.err.supplier_required',
        'post_limit_reached': 'feed.err.post_limit',
        'follow_limit_reached': 'feed.err.follow_limit',
        'comment_limit_reached': 'feed.err.comment_limit',
        'cannot_follow_self': 'feed.err.follow_self',
        'cannot_report_own': 'feed.err.report_own',
        'not_found': 'feed.err.not_found',
        'unauthenticated': 'feed.err.auth',
        'forbidden': 'feed.err.forbidden',
        'validation_error': 'feed.err.validation',
        'timeout': 'feed.err.network',
        'network_error': 'feed.err.network',
        'rate_limited': 'feed.err.rate_limited',
      };
      expected.forEach((code, key) {
        expect(describeFeedError(_api(400, code)).key, key, reason: code);
      });
    });

    test('status fallbacks and Retry-After', () {
      expect(describeFeedError(_api(401, 'http_401')).key, 'feed.err.auth');
      expect(describeFeedError(_api(403, 'http_403')).key, 'feed.err.forbidden');
      expect(describeFeedError(_api(500, 'http_500')).key, 'feed.err.generic');
      expect(describeFeedError(StateError('x')).key, 'feed.err.generic');
      final s = describeFeedError(_api(429, 'rate_limited', retry: 30));
      expect(s.key, 'feed.err.rate_limited_s');
      expect(s.args['n'], '30');
      final m = describeFeedError(_api(429, 'rate_limited', retry: 125));
      expect(m.key, 'feed.err.rate_limited_m');
      expect(m.args['n'], '3');
      expect(describeFeedError(_api(429, 'http_429')).key, 'feed.err.rate_limited');
    });
  });

  group('live repository (fake Dio)', () {
    test('home sends limit + cursor and parses source', () async {
      final a = _Adapter((o) => _Reply(_load('feed_home_page')));
      final repo = _live(a);
      final page = await repo.home(cursor: 'abc', limit: 10);
      expect(a.calls.single.method, 'GET');
      expect(a.calls.single.path, '/v1/feed/home');
      expect(a.calls.single.queryParameters, <String, dynamic>{'limit': 10, 'cursor': 'abc'});
      expect(page.source, FeedSource.trending);
      await repo.home();
      expect(a.calls.last.queryParameters.containsKey('cursor'), isFalse);
      await repo.trending(limit: 500);
      expect(a.calls.last.queryParameters['limit'], 50);
    });

    test('verbs and paths', () async {
      final a = _Adapter((o) {
        final p = o.path;
        if (p.endsWith('/like')) return _Reply(_load('feed_like_state'));
        if (p.endsWith('/follow')) return _Reply(_load('feed_follow_state'));
        if (p.endsWith('/comments') && o.method == 'POST') {
          return const _Reply(<String, dynamic>{
            'id': 'cmt_9', 'post_id': 'pst_1', 'user_id': 'u', 'body': 'hi', 'created_at': '2026-10-12T10:00:00Z',
          }, 201);
        }
        if (p.endsWith('/report')) return const _Reply(<String, dynamic>{'status': 'received'}, 202);
        if (o.method == 'DELETE') return const _Reply(null, 204);
        return _Reply(_load('feed_post'));
      });
      final repo = _live(a);
      await repo.like('pst_1');
      expect(a.calls.last.method, 'PUT');
      expect(a.calls.last.path, '/v1/feed/posts/pst_1/like');
      await repo.unlike('pst_1');
      expect(a.calls.last.method, 'DELETE');
      await repo.follow('sup_cn_001');
      expect(a.calls.last.method, 'POST');
      expect(a.calls.last.path, '/v1/feed/suppliers/sup_cn_001/follow');
      final st = await repo.unfollow('sup_cn_001');
      expect(a.calls.last.method, 'DELETE');
      expect(st.followerCount, 12);
      final c = await repo.addComment('pst_1', '  hi  ');
      expect(c.id, 'cmt_9');
      expect(a.calls.last.data, <String, dynamic>{'body': 'hi'});
      await repo.reportPost('pst_1', ReportReason.scamOrFraud, details: ' x ');
      expect(a.calls.last.path, '/v1/feed/posts/pst_1/report');
      expect(a.calls.last.data, <String, dynamic>{'reason': 'scam_or_fraud', 'details': 'x'});
      await repo.reportComment('cmt_9', ReportReason.spam);
      expect(a.calls.last.data, <String, dynamic>{'reason': 'spam'});
      await repo.deleteComment('cmt_9');
      expect(a.calls.last.path, '/v1/feed/comments/cmt_9');
      await repo.deletePost('pst_1');
      expect(a.calls.last.path, '/v1/feed/posts/pst_1');
      await repo.createPost(const PostDraft(
        body: ' text ',
        media: <String>['/v1/media/files/0123456789abcdef0123456789abcdef.jpg'],
        tags: <String>['led'],
        listingRef: 'lst_1',
      ));
      expect(a.calls.last.path, '/v1/feed/posts');
      expect(a.calls.last.data, <String, dynamic>{
        'body': 'text',
        'media': <String>['/v1/media/files/0123456789abcdef0123456789abcdef.jpg'],
        'tags': <String>['led'],
        'listing_ref': 'lst_1',
      });
    });

    test('following list and supplier posts', () async {
      final a = _Adapter((o) => o.path.endsWith('/following')
          ? _Reply(_load('feed_following_page'))
          : _Reply(_load('feed_home_page')));
      final repo = _live(a);
      final f = await repo.following();
      expect(f.items, hasLength(2));
      final p = await repo.supplierPosts('sup_cn_001', cursor: 'c1');
      expect(a.calls.last.path, '/v1/feed/suppliers/sup_cn_001/posts');
      expect(p.items, hasLength(2));
    });

    test('error bodies map to codes', () async {
      Future<ApiException> failure(_Reply r, Future<void> Function(LiveFeedRepository) call) async {
        final repo = _live(_Adapter((_) => r));
        try {
          await call(repo);
        } on ApiException catch (e) {
          return e;
        }
        fail('expected ApiException');
      }

      final rejected = await failure(
        _Reply(_load('error_feed_content_rejected'), 422),
        (r) => r.createPost(const PostDraft(body: 'x')),
      );
      expect(rejected.code, 'content_rejected');
      expect(rejected.status, 422);
      expect(describeFeedError(rejected).key, 'feed.err.content_rejected');

      final limited = await failure(
        _Reply(_load('error_feed_rate_limited'), 429, const {'retry-after': '125'}),
        (r) => r.createPost(const PostDraft(body: 'x')),
      );
      expect(limited.code, 'rate_limited');
      expect(limited.retryAfterSeconds, 125);
      expect(describeFeedError(limited).key, 'feed.err.rate_limited_m');

      final sup = await failure(
        _Reply(_load('error_feed_supplier_required'), 403),
        (r) => r.createPost(const PostDraft(body: 'x')),
      );
      expect(describeFeedError(sup).key, 'feed.err.supplier_required');

      final cur = await failure(
        _Reply(_load('error_feed_invalid_cursor'), 422),
        (r) => r.home(cursor: 'bad'),
      );
      expect(describeFeedError(cur).key, 'feed.err.invalid_cursor');

      final cap = await failure(
        _Reply(_load('error_feed_post_limit'), 409),
        (r) => r.createPost(const PostDraft(body: 'x')),
      );
      expect(describeFeedError(cap).key, 'feed.err.post_limit');
    });
  });

  group('mock repository', () {
    test('keyset pagination covers everything once', () async {
      final repo = MockFeedRepository();
      final seen = <String>[];
      String? cursor;
      var pages = 0;
      do {
        final page = await repo.trending(cursor: cursor, limit: 5);
        seen.addAll(page.items.map((p) => p.id));
        cursor = page.nextCursor;
        pages++;
      } while (cursor != null && pages < 10);
      expect(pages, 3);
      expect(seen.toSet(), hasLength(seen.length));
      expect(seen, hasLength(14));
    });

    test('invalid cursor is 422 invalid_cursor', () async {
      final repo = MockFeedRepository();
      await expectLater(
        repo.trending(cursor: 'garbage'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid_cursor')),
      );
      await expectLater(
        repo.supplierPosts('sup_cn_001', cursor: 't:1'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 422)),
      );
    });

    test('home falls back to trending, then follows', () async {
      final repo = MockFeedRepository();
      expect((await repo.home()).source, FeedSource.trending);
      await repo.follow('sup_cn_002');
      final page = await repo.home();
      expect(page.source, FeedSource.following);
      expect(page.items.every((p) => p.supplierId == 'sup_cn_002'), isTrue);
      expect(page.nextCursor, isNull);
    });

    test('like and follow are idempotent', () async {
      final repo = MockFeedRepository();
      final before = (await repo.trending()).items.first;
      final a = await repo.like(before.id);
      final b = await repo.like(before.id);
      expect(a.likeCount, before.likeCount + 1);
      expect(b.likeCount, a.likeCount);
      final c = await repo.unlike(before.id);
      final d = await repo.unlike(before.id);
      expect(c.likeCount, before.likeCount);
      expect(d.likeCount, before.likeCount);
      expect((await repo.follow('sup_cn_001')).following, isTrue);
      expect((await repo.follow('sup_cn_001')).following, isTrue);
      expect((await repo.unfollow('sup_cn_001')).following, isFalse);
    });

    test('publishing rules', () async {
      final anon = MockFeedRepository();
      await expectLater(
        anon.createPost(const PostDraft(body: 'hello')),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'supplier_required')),
      );
      final repo = MockFeedRepository(supplierId: () => 'sup_cn_001', postLimit: 2);
      await expectLater(
        repo.createPost(const PostDraft(body: 'call 0770 123 4567')),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'content_rejected')),
      );
      final ok = await repo.createPost(const PostDraft(body: 'fresh news', tags: <String>['led']));
      expect(ok.supplierId, 'sup_cn_001');
      expect((await repo.supplierPosts('sup_cn_001')).items.first.id, ok.id);
      await expectLater(
        repo.createPost(const PostDraft(body: 'again')),
        throwsA(isA<ApiException>()
            .having((e) => e.status, 'status', 429)
            .having((e) => e.retryAfterSeconds, 'retry', isNotNull)),
      );
      await expectLater(
        repo.follow('sup_cn_001'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'cannot_follow_self')),
      );
    });

    test('comments: add, delete rules, report own', () async {
      final repo = MockFeedRepository(userId: () => 'usr_me');
      final post = (await repo.trending()).items.first;
      final c = await repo.addComment(post.id, 'hello');
      expect((await repo.getPost(post.id)).commentCount, post.commentCount + 1);
      await expectLater(
        repo.reportComment(c.id, ReportReason.spam),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'cannot_report_own')),
      );
      await expectLater(
        repo.deleteComment('cmt_seed_0_0'),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 403)),
      );
      await repo.deleteComment(c.id);
      expect((await repo.getPost(post.id)).commentCount, post.commentCount);
    });
  });

  group('controllers', () {
    test('optimistic like then server state', () async {
      final repo = _GatedRepo();
      final c = _container(repo);
      final p = (await repo.trending()).items.first;
      c.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[p]);
      repo.gate = Completer<void>();
      final f = c.read(feedActionsProvider).toggleLike(p.id);
      var cur = c.read(feedPostStoreProvider)[p.id]!;
      expect(cur.viewerLiked, isTrue);
      expect(cur.likeCount, p.likeCount + 1);
      repo.gate!.complete();
      await f;
      cur = c.read(feedPostStoreProvider)[p.id]!;
      expect(cur.viewerLiked, isTrue);
      expect(cur.likeCount, p.likeCount + 1);
      // And back.
      await c.read(feedActionsProvider).toggleLike(p.id);
      cur = c.read(feedPostStoreProvider)[p.id]!;
      expect(cur.viewerLiked, isFalse);
      expect(cur.likeCount, p.likeCount);
    });

    test('failed like rolls back and rethrows', () async {
      final repo = _GatedRepo();
      final c = _container(repo);
      final p = (await repo.trending()).items.first;
      c.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[p]);
      repo.gate = Completer<void>();
      repo.failWith = _api(429, 'rate_limited', retry: 60);
      final f = c.read(feedActionsProvider).toggleLike(p.id);
      final done = expectLater(
        f,
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 429)),
      );
      expect(c.read(feedPostStoreProvider)[p.id]!.viewerLiked, isTrue);
      repo.gate!.complete();
      await done;
      final cur = c.read(feedPostStoreProvider)[p.id]!;
      expect(cur.viewerLiked, p.viewerLiked);
      expect(cur.likeCount, p.likeCount);
    });

    test('second tap while in flight is ignored', () async {
      final repo = _GatedRepo();
      final c = _container(repo);
      final p = (await repo.trending()).items.first;
      c.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[p]);
      repo.gate = Completer<void>();
      final a = c.read(feedActionsProvider);
      final f1 = a.toggleLike(p.id);
      final f2 = a.toggleLike(p.id);
      repo.gate!.complete();
      await Future.wait(<Future<void>>[f1, f2]);
      expect(repo.likeCalls, 1);
      expect(c.read(feedPostStoreProvider)[p.id]!.likeCount, p.likeCount + 1);
    });

    test('follow toggles optimistically and rolls back', () async {
      final repo = _GatedRepo();
      final ctrl = FollowingController(repo, autoLoad: false);
      addTearDown(ctrl.dispose);
      await ctrl.toggle('sup_cn_001');
      expect(ctrl.state.isFollowing('sup_cn_001'), isTrue);
      await ctrl.toggle('sup_cn_001');
      expect(ctrl.state.isFollowing('sup_cn_001'), isFalse);
      repo.failWith = _api(409, 'follow_limit_reached');
      await expectLater(
        ctrl.toggle('sup_cn_002'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'follow_limit_reached')),
      );
      expect(ctrl.state.isFollowing('sup_cn_002'), isFalse);
      expect(ctrl.state.busy, isEmpty);
    });

    test('following load reads existing follows', () async {
      final repo = MockFeedRepository(initialFollows: <String>{'sup_cn_003'});
      final ctrl = FollowingController(repo);
      addTearDown(ctrl.dispose);
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(ctrl.state.loaded, isTrue);
      expect(ctrl.state.isFollowing('sup_cn_003'), isTrue);
    });

    test('list: load more appends without duplicates, refresh resets', () async {
      final repo = MockFeedRepository();
      final store = PostStore();
      final ctrl = FeedListController(store, (c) => repo.trending(cursor: c, limit: 5));
      addTearDown(ctrl.dispose);
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(ctrl.state.loading, isFalse);
      expect(ctrl.state.ids, hasLength(5));
      expect(ctrl.state.hasMore, isTrue);
      await ctrl.loadMore();
      await ctrl.loadMore();
      expect(ctrl.state.ids, hasLength(14));
      expect(ctrl.state.ids.toSet(), hasLength(14));
      expect(ctrl.state.hasMore, isFalse);
      expect(store.state, hasLength(14));
      await ctrl.refresh();
      expect(ctrl.state.ids, hasLength(5));
    });

    test('list: failures are kept and recoverable', () async {
      final repo = MockFeedRepository();
      var fail = true;
      final ctrl = FeedListController(PostStore(), (c) async {
        if (fail) throw _api(500, 'http_500');
        return repo.trending(cursor: c, limit: 5);
      });
      addTearDown(ctrl.dispose);
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(ctrl.state.error, isA<ApiException>());
      expect(ctrl.state.ids, isEmpty);
      fail = false;
      await ctrl.refresh();
      expect(ctrl.state.error, isNull);
      expect(ctrl.state.ids, hasLength(5));
      fail = true;
      await ctrl.loadMore();
      expect(ctrl.state.moreError, isA<ApiException>());
      expect(ctrl.state.ids, hasLength(5));
    });
  });

  group('widgets', () {
    testWidgets('feed screen shows trending for guests and likes optimistically',
        (tester) async {
      final repo = _GatedRepo();
      final first = (await repo.trending()).items.first;
      await _pump(tester, const FeedScreen(), overrides: _overrides(repo));
      expect(find.byKey(ValueKey<String>('feed-like-${first.id}')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('feed-mode-trending')), findsOneWidget);
      final likeBtn = tester.widget<TextButton>(find.byKey(ValueKey<String>('feed-like-${first.id}')));
      likeBtn.onPressed!();
      await tester.pump();
      expect(
        tester.widget<Text>(find.byKey(ValueKey<String>('feed-like-count-${first.id}'))).data,
        '${first.likeCount + 1}',
      );
      await settle(tester);
      expect(tester.takeException(), isNull);
    });

    testWidgets('failed like shows a localized message and restores the count',
        (tester) async {
      final repo = _GatedRepo();
      final first = (await repo.trending()).items.first;
      await _pump(tester, const FeedScreen(), overrides: _overrides(repo));
      repo.failWith = _api(429, 'rate_limited', retry: 30);
      tester.widget<TextButton>(find.byKey(ValueKey<String>('feed-like-${first.id}'))).onPressed!();
      await settle(tester);
      expect(
        tester.widget<Text>(find.byKey(ValueKey<String>('feed-like-count-${first.id}'))).data,
        '${first.likeCount}',
      );
      expect(find.textContaining('30'), findsWidgets);
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('load more pulls the next page', (tester) async {
      final repo = _GatedRepo()..pageCap = 5;
      await _pump(tester, const FeedScreen(), overrides: _overrides(repo));
      final container = ProviderScope.containerOf(tester.element(find.byType(FeedScreen)));
      expect(container.read(feedListProvider('trending')).ids, hasLength(5));
      await tester.dragUntilVisible(
        find.byKey(const ValueKey<String>('feed-load-more')),
        find.byKey(const ValueKey<String>('feed-list-trending')),
        const Offset(0, -300),
      );
      tester.widget<OutlinedButton>(find.byKey(const ValueKey<String>('feed-load-more'))).onPressed!();
      await settle(tester);
      expect(container.read(feedListProvider('trending')).ids, hasLength(10));
    });

    testWidgets('signed-in user without follows sees the trending fallback banner', (tester) async {
      final repo = _GatedRepo();
      await _pump(tester, const FeedScreen(), overrides: _overrides(repo, me: _buyerMe));
      expect(find.byKey(const ValueKey<String>('feed-fallback-banner')), findsOneWidget);
    });

    testWidgets('post card is overflow safe at text scale 2.0 on 360dp', (tester) async {
      final repo = MockFeedRepository();
      final post = FeedPost(
        id: 'post_big',
        supplierId: 'sup_cn_001',
        body: 'A very long post text ' * 30,
        media: List<String>.generate(
          5,
          (i) => '/v1/media/files/${'a' * 31}$i.jpg',
        ),
        tags: const <String>['led', 'solar', 'new_stock', 'wholesale', 'factory'],
        listingRef: 'lst_0041',
        likeCount: 12345,
        commentCount: 678,
        createdAt: DateTime.utc(2026, 10, 1),
      );
      await _pump(
        tester,
        Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: PostCard(postId: post.id),
          ),
        ),
        overrides: <Override>[
          ..._overrides(repo, me: _buyerMe),
          feedPostStoreProvider.overrideWith((ref) => PostStore()..putAll(<FeedPost>[post])),
        ],
        textScale: 2.0,
      );
      await settle(tester);
      expect(tester.takeException(), isNull);
      expect(find.byKey(const ValueKey<String>('feed-media-grid')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('feed-listing-post_big')), findsOneWidget);
    });

    testWidgets('listing chip opens the listing', (tester) async {
      final repo = MockFeedRepository();
      final post = FeedPost(
        id: 'post_l',
        supplierId: 'sup_cn_001',
        body: 'hello',
        listingRef: 'lst_0041',
        createdAt: DateTime.utc(2026, 10, 1),
      );
      await _pump(
        tester,
        Scaffold(body: PostCard(postId: post.id)),
        overrides: <Override>[
          ..._overrides(repo),
          feedPostStoreProvider.overrideWith((ref) => PostStore()..putAll(<FeedPost>[post])),
        ],
      );
      tester.widget<ActionChip>(find.byKey(const ValueKey<String>('feed-listing-post_l'))).onPressed!();
      await settle(tester);
      expect(find.text('listing-lst_0041'), findsOneWidget);
    });

    testWidgets('follow button toggles and rolls back on error', (tester) async {
      final repo = _GatedRepo();
      await _pump(
        tester,
        const Scaffold(body: Center(child: FollowButton(supplierId: 'sup_cn_001'))),
        overrides: _overrides(repo),
      );
      const key = ValueKey<String>('feed-follow-sup_cn_001');
      expect(find.byType(FilledButton), findsOneWidget);
      tester.widget<FilledButton>(find.byKey(key)).onPressed!();
      await settle(tester);
      expect(find.byType(OutlinedButton), findsOneWidget);
      repo.failWith = _api(429, 'rate_limited', retry: 10);
      tester.widget<OutlinedButton>(find.byKey(key)).onPressed!();
      await settle(tester);
      expect(find.byType(OutlinedButton), findsOneWidget, reason: 'still following after the failed unfollow');
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('own supplier gets no follow button', (tester) async {
      await _pump(
        tester,
        const Scaffold(body: Center(child: FollowButton(supplierId: 'sup_cn_001'))),
        overrides: _overrides(MockFeedRepository(), me: _supplierMe),
      );
      expect(find.byType(FilledButton), findsNothing);
      expect(find.byType(OutlinedButton), findsNothing);
    });

    testWidgets('detail: add a comment (client check, then server)', (tester) async {
      final repo = MockFeedRepository(userId: () => _buyerMe.id);
      final post = (await repo.trending()).items.first;
      await _pump(
        tester,
        PostDetailScreen(postId: post.id),
        overrides: _overrides(repo, me: _buyerMe),
      );
      final container = ProviderScope.containerOf(tester.element(find.byType(PostDetailScreen)));
      final field = find.byKey(const ValueKey<String>('feed-comment-field'));
      await tester.enterText(field, 'write me at a@b.com');
      tester.widget<IconButton>(find.byKey(const ValueKey<String>('feed-comment-send'))).onPressed!();
      await settle(tester);
      expect(container.read(feedCommentsProvider(post.id)).items.any((c) => c.body.contains('a@b.com')), isFalse);
      expect(find.byType(TextField), findsOneWidget);

      final before = container.read(feedPostProvider(post.id))!.commentCount;
      await tester.enterText(field, 'Great, what is the MOQ?');
      tester.widget<IconButton>(find.byKey(const ValueKey<String>('feed-comment-send'))).onPressed!();
      await settle(tester);
      final comments = container.read(feedCommentsProvider(post.id)).items;
      expect(comments.last.body, 'Great, what is the MOQ?');
      expect(container.read(feedPostProvider(post.id))!.commentCount, before + 1);

      // Delete it again.
      final mine = comments.last;
      await container.read(feedCommentsProvider(post.id).notifier).delete(mine.id);
      expect(container.read(feedCommentsProvider(post.id)).items.any((c) => c.id == mine.id), isFalse);
      expect(container.read(feedPostProvider(post.id))!.commentCount, before);
      expect(tester.takeException(), isNull);
    });

    testWidgets('detail for a guest asks to sign in', (tester) async {
      final repo = MockFeedRepository();
      final post = (await repo.trending()).items.first;
      await _pump(tester, PostDetailScreen(postId: post.id), overrides: _overrides(repo));
      expect(find.byKey(const ValueKey<String>('feed-comment-login')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('feed-comment-field')), findsNothing);
    });

    testWidgets('detail of a missing post shows an error', (tester) async {
      await _pump(tester, const PostDetailScreen(postId: 'post_nope'), overrides: _overrides(MockFeedRepository()));
      expect(find.byType(ErrorState), findsOneWidget);
    });

    testWidgets('report sheet sends the chosen reason', (tester) async {
      ReportReason? sent;
      String? sentDetails;
      await _pump(
        tester,
        Scaffold(
          body: Builder(
            builder: (ctx) => ElevatedButton(
              key: const ValueKey<String>('open-report'),
              onPressed: () => showModalBottomSheet<void>(
                context: ctx,
                isScrollControlled: true,
                builder: (_) => FeedReportSheet(onSubmit: (r, d) async {
                  sent = r;
                  sentDetails = d;
                }),
              ),
              child: const Text('open'),
            ),
          ),
        ),
        overrides: _overrides(MockFeedRepository()),
      );
      await tester.tap(find.byKey(const ValueKey<String>('open-report')));
      await settle(tester, frames: 5);
      expect(
        tester.widget<FilledButton>(find.byKey(const ValueKey<String>('feed-report-send'))).onPressed,
        isNull,
      );
      tester.widget<ChoiceChip>(find.byKey(const ValueKey<String>('feed-report-spam'))).onSelected!(true);
      await tester.pump();
      await tester.enterText(find.byKey(const ValueKey<String>('feed-report-details')), 'bad stuff');
      tester.widget<FilledButton>(find.byKey(const ValueKey<String>('feed-report-send'))).onPressed!();
      await settle(tester);
      expect(sent, ReportReason.spam);
      expect(sentDetails, 'bad stuff');
    });

    testWidgets('report sheet shows the 429 message with the wait', (tester) async {
      await _pump(
        tester,
        Scaffold(
          body: FeedReportSheet(onSubmit: (r, d) async => throw _api(429, 'rate_limited', retry: 125)),
        ),
        overrides: _overrides(MockFeedRepository()),
        textScale: 2.0,
      );
      tester.widget<ChoiceChip>(find.byKey(const ValueKey<String>('feed-report-other'))).onSelected!(true);
      await tester.pump();
      tester.widget<FilledButton>(find.byKey(const ValueKey<String>('feed-report-send'))).onPressed!();
      await settle(tester);
      expect(find.byKey(const ValueKey<String>('feed-report-error')), findsOneWidget);
      expect(
        tester.widget<Text>(find.byKey(const ValueKey<String>('feed-report-error'))).data,
        contains('3'),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('composer is gated for guests and non-suppliers', (tester) async {
      await _pump(tester, const ComposerScreen(), overrides: _overrides(MockFeedRepository()));
      expect(find.byKey(const ValueKey<String>('feed-composer-body')), findsNothing);
      expect(find.byKey(const ValueKey<String>('feed-composer-gate-action')), findsOneWidget);
    });

    testWidgets('composer blocks contact details client-side, then publishes', (tester) async {
      final repo = _GatedRepo(supplierId: () => 'sup_cn_001');
      final router = await _pump(
        tester,
        const _Launcher(),
        overrides: _overrides(repo, me: _supplierMe),
      );
      router.push('/compose');
      await settle(tester);
      expect(find.byKey(const ValueKey<String>('feed-composer-body')), findsOneWidget);

      Future<void> submit() async {
        await tester.drag(find.byType(ListView).first, const Offset(0, -900));
        await tester.pump();
        tester
            .widget<PrimaryButton>(find.byKey(const ValueKey<String>('feed-composer-publish')))
            .onPressed!();
        await settle(tester);
      }

      await tester.enterText(
        find.byKey(const ValueKey<String>('feed-composer-body')),
        'Order now, call 0770 123 4567',
      );
      await submit();
      expect(repo.createCalls, 0);
      await tester.drag(find.byType(ListView).first, const Offset(0, 900));
      await tester.pump();
      expect(find.textContaining('أزل'), findsWidgets);
      await tester.enterText(
        find.byKey(const ValueKey<String>('feed-composer-body')),
        'Fresh stock arrived',
      );
      await tester.enterText(find.byKey(const ValueKey<String>('feed-composer-tags')), 'led, Solar');
      await submit();
      expect(repo.createCalls, 1);
      // Popped back to the launcher.
      expect(find.text('launcher'), findsOneWidget);
      final container = ProviderScope.containerOf(tester.element(find.text('launcher')));
      final mine = await repo.supplierPosts('sup_cn_001');
      expect(mine.items.first.body, 'Fresh stock arrived');
      expect(mine.items.first.tags, <String>['led', 'solar']);
      expect(container.read(feedPostStoreProvider).containsKey(mine.items.first.id), isTrue);
    });

    testWidgets('composer shows the server rate limit message', (tester) async {
      final repo = _GatedRepo(supplierId: () => 'sup_cn_001', postLimit: 0);
      final router = await _pump(
        tester,
        const _Launcher(),
        overrides: _overrides(repo, me: _supplierMe),
      );
      router.push('/compose');
      await settle(tester);
      await tester.enterText(find.byKey(const ValueKey<String>('feed-composer-body')), 'hello world');
      await tester.drag(find.byType(ListView).first, const Offset(0, -900));
      await tester.pump();
      tester
          .widget<PrimaryButton>(find.byKey(const ValueKey<String>('feed-composer-publish')))
          .onPressed!();
      await settle(tester);
      expect(find.byKey(const ValueKey<String>('feed-composer-error')), findsOneWidget);
      expect(find.text('launcher'), findsNothing);
    });
  });
}

class _Launcher extends StatelessWidget {
  const _Launcher();

  @override
  Widget build(BuildContext context) => const Scaffold(body: Text('launcher'));
}
