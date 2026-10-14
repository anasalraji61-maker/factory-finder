import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class FeedRepository {
  Future<FeedPage<FeedPost>> home({String? cursor, int limit = kFeedPageSize});
  Future<FeedPage<FeedPost>> trending({String? cursor, int limit = kFeedPageSize});
  Future<FeedPage<FeedPost>> supplierPosts(String supplierId,
      {String? cursor, int limit = kFeedPageSize});
  Future<FeedPost> getPost(String postId);
  Future<FeedPost> createPost(PostDraft draft);
  Future<void> deletePost(String postId);

  Future<FeedPage<FollowedSupplier>> following({String? cursor, int limit = 50});
  Future<FollowState> follow(String supplierId);
  Future<FollowState> unfollow(String supplierId);

  Future<LikeState> like(String postId);
  Future<LikeState> unlike(String postId);

  Future<FeedPage<FeedComment>> comments(String postId,
      {String? cursor, int limit = kFeedPageSize});
  Future<FeedComment> addComment(String postId, String body);
  Future<void> deleteComment(String commentId);

  Future<void> reportPost(String postId, ReportReason reason, {String? details});
  Future<void> reportComment(String commentId, ReportReason reason, {String? details});
}

class LiveFeedRepository implements FeedRepository {
  LiveFeedRepository(this._api);

  final ApiClient _api;

  static String _e(String s) => Uri.encodeComponent(s);

  Map<String, dynamic> _page(String? cursor, int limit) => <String, dynamic>{
        'limit': limit.clamp(1, 50).toInt(),
        if (cursor != null && cursor.isNotEmpty) 'cursor': cursor,
      };

  FeedPost _post(Object? json) {
    if (json is Map) return FeedPost.fromJson(json);
    throw ApiException(status: 502, code: 'bad_response', message: 'Unexpected feed response');
  }

  @override
  Future<FeedPage<FeedPost>> home({String? cursor, int limit = kFeedPageSize}) async =>
      FeedPage.parse(await _api.get('/v1/feed/home', query: _page(cursor, limit)), FeedPost.fromJson);

  @override
  Future<FeedPage<FeedPost>> trending({String? cursor, int limit = kFeedPageSize}) async =>
      FeedPage.parse(
          await _api.get('/v1/feed/trending', query: _page(cursor, limit)), FeedPost.fromJson);

  @override
  Future<FeedPage<FeedPost>> supplierPosts(String supplierId,
          {String? cursor, int limit = kFeedPageSize}) async =>
      FeedPage.parse(
        await _api.get('/v1/feed/suppliers/${_e(supplierId)}/posts', query: _page(cursor, limit)),
        FeedPost.fromJson,
      );

  @override
  Future<FeedPost> getPost(String postId) async =>
      _post(await _api.get('/v1/feed/posts/${_e(postId)}'));

  @override
  Future<FeedPost> createPost(PostDraft draft) async =>
      _post(await _api.post('/v1/feed/posts', body: draft.toJson()));

  @override
  Future<void> deletePost(String postId) async {
    await _api.delete('/v1/feed/posts/${_e(postId)}');
  }

  @override
  Future<FeedPage<FollowedSupplier>> following({String? cursor, int limit = 50}) async =>
      FeedPage.parse(
          await _api.get('/v1/feed/following', query: _page(cursor, limit)), FollowedSupplier.fromJson);

  @override
  Future<FollowState> follow(String supplierId) async => FollowState.fromJson(
        await _api.post('/v1/feed/suppliers/${_e(supplierId)}/follow'),
      );

  @override
  Future<FollowState> unfollow(String supplierId) async => FollowState.fromJson(
        await _api.delete('/v1/feed/suppliers/${_e(supplierId)}/follow'),
      );

  @override
  Future<LikeState> like(String postId) async =>
      LikeState.fromJson(await _api.put('/v1/feed/posts/${_e(postId)}/like'));

  @override
  Future<LikeState> unlike(String postId) async =>
      LikeState.fromJson(await _api.delete('/v1/feed/posts/${_e(postId)}/like'));

  @override
  Future<FeedPage<FeedComment>> comments(String postId,
          {String? cursor, int limit = kFeedPageSize}) async =>
      FeedPage.parse(
        await _api.get('/v1/feed/posts/${_e(postId)}/comments', query: _page(cursor, limit)),
        FeedComment.fromJson,
      );

  @override
  Future<FeedComment> addComment(String postId, String body) async => FeedComment.fromJson(
        await _api.post('/v1/feed/posts/${_e(postId)}/comments', body: {'body': body.trim()}),
      );

  @override
  Future<void> deleteComment(String commentId) async {
    await _api.delete('/v1/feed/comments/${_e(commentId)}');
  }

  Map<String, dynamic> _report(ReportReason reason, String? details) {
    final d = details?.trim() ?? '';
    return <String, dynamic>{
      'reason': reason.json,
      if (d.isNotEmpty) 'details': d.length > kReportDetailsMax ? d.substring(0, kReportDetailsMax) : d,
    };
  }

  @override
  Future<void> reportPost(String postId, ReportReason reason, {String? details}) async {
    await _api.post('/v1/feed/posts/${_e(postId)}/report', body: _report(reason, details));
  }

  @override
  Future<void> reportComment(String commentId, ReportReason reason, {String? details}) async {
    await _api.post('/v1/feed/comments/${_e(commentId)}/report', body: _report(reason, details));
  }
}

final RegExp _mediaPathRe = RegExp(r'^/v1/media/files/[0-9a-f]{32}\.(?:jpg|png|webp)$');

/// In-memory backend with deterministic seed data. It mirrors the server's
/// rules closely enough for UI work: keyset cursors, idempotent like/follow,
/// screening, caps, per-hour post limit and error codes.
class MockFeedRepository implements FeedRepository {
  MockFeedRepository({
    String Function()? userId,
    String? Function()? supplierId,
    Set<String> initialFollows = const <String>{},
    this.delayMs = 0,
    this.postLimit = 10,
    DateTime Function()? clock,
  })  : _userId = userId ?? (() => kMockUserId),
        _supplierId = supplierId ?? (() => null),
        _follows = <String>{...initialFollows},
        _clock = clock ?? DateTime.now {
    _seed();
  }

  final String Function() _userId;
  final String? Function() _supplierId;
  final int delayMs;
  final int postLimit;
  final DateTime Function() _clock;

  final Set<String> _follows;
  final Set<String> _liked = <String>{};
  final Set<String> _reported = <String>{};
  final List<FeedPost> _posts = <FeedPost>[]; // newest first
  final Map<String, List<FeedComment>> _comments = <String, List<FeedComment>>{};
  int _postSeq = 0;
  int _commentSeq = 0;
  int _created = 0;

  static const List<String> _suppliers = <String>[
    'sup_cn_001',
    'sup_cn_002',
    'sup_cn_003',
    'sup_cn_004',
    'sup_cn_005',
  ];

  void _seed() {
    final base = DateTime.utc(2026, 10, 12, 9);
    const bodies = <String>[
      'New batch of LED panels is ready to ship. MOQ 500 pieces, samples available.',
      'دفعة جديدة من الأقمشة القطنية بجودة عالية، الحد الأدنى للطلب 200 متر.',
      'Our CNC line was upgraded this month: tolerance now 0.01 mm.',
      'Factory tour photos from this week. Packing line is running two shifts.',
      'خصم خاص على الطلبات الكبيرة حتى نهاية الشهر.',
      'Recycled PP granules back in stock, certificates available on request.',
      'We shipped 14 containers to Basra this quarter.',
      'مصنعنا يضيف خط تغليف جديداً لتسريع التسليم.',
    ];
    for (var i = 0; i < 14; i++) {
      _postSeq++;
      final id = 'post_${_postSeq.toString().padLeft(3, '0')}';
      _posts.add(FeedPost(
        id: id,
        supplierId: _suppliers[i % _suppliers.length],
        body: bodies[i % bodies.length],
        media: i % 3 == 0
            ? List<String>.generate(
                (i % 5) + 1,
                (k) => '/v1/media/files/${(i * 7 + k).toRadixString(16).padLeft(32, '0')}.jpg',
              )
            : const <String>[],
        tags: i.isEven ? <String>['factory', 'new_stock'] : const <String>['offer'],
        listingRef: i % 4 == 0 ? 'lst_${(41 + i).toString().padLeft(4, '0')}' : null,
        likeCount: 3 + (i * 5) % 17,
        commentCount: i < 3 ? 2 : 0,
        createdAt: base.subtract(Duration(hours: i * 7)),
      ));
    }
    for (var i = 0; i < 3; i++) {
      final id = _posts[i].id;
      _comments[id] = <FeedComment>[
        for (var k = 0; k < 2; k++)
          FeedComment(
            id: 'cmt_seed_${i}_$k',
            postId: id,
            userId: k == 0 ? 'usr_a' : 'usr_b',
            body: k == 0 ? 'Interested, please share the price list.' : 'ممتاز، هل يتوفر الشحن لبغداد؟',
            createdAt: base.subtract(Duration(hours: i * 7 - k - 1)),
          ),
      ];
    }
  }

  Future<void> _wait() async {
    if (delayMs > 0) await mockDelay(delayMs);
  }

  ApiException _err(int status, String code, [int? retryAfter]) =>
      ApiException(status: status, code: code, message: code, retryAfterSeconds: retryAfter);

  FeedPost _view(FeedPost p) => p.copyWith(viewerLiked: _liked.contains(p.id));

  FeedPost _find(String id) {
    for (final p in _posts) {
      if (p.id == id) return p;
    }
    throw _err(404, 'not_found');
  }

  void _replace(FeedPost p) {
    final i = _posts.indexWhere((x) => x.id == p.id);
    if (i >= 0) _posts[i] = p;
  }

  /// Cursor format `<prefix>:<offset>`; [prefix] separates listings.
  int _offset(String? cursor, String prefix) {
    if (cursor == null || cursor.isEmpty) return 0;
    final parts = cursor.split(':');
    final n = parts.length == 2 ? int.tryParse(parts[1]) : null;
    if (parts.length != 2 || parts[0] != prefix || n == null || n < 0) {
      throw _err(422, 'invalid_cursor');
    }
    return n;
  }

  FeedPage<T> _slice<T>(List<T> all, int offset, int limit, String prefix, {FeedSource? source}) {
    final end = (offset + limit).clamp(0, all.length).toInt();
    final items = offset >= all.length ? <T>[] : all.sublist(offset, end);
    return FeedPage<T>(
      items: items,
      nextCursor: end < all.length ? '$prefix:$end' : null,
      source: source,
    );
  }

  List<FeedPost> _trendingOrder() {
    final l = List<FeedPost>.of(_posts);
    int score(FeedPost p) => p.likeCount + 2 * p.commentCount;
    l.sort((a, b) {
      final c = score(b).compareTo(score(a));
      if (c != 0) return c;
      return (b.createdAt ?? DateTime(2000)).compareTo(a.createdAt ?? DateTime(2000));
    });
    return l;
  }

  @override
  Future<FeedPage<FeedPost>> trending({String? cursor, int limit = kFeedPageSize}) async {
    await _wait();
    final off = _offset(cursor, 't');
    final page = _slice(_trendingOrder(), off, limit, 't', source: FeedSource.trending);
    return FeedPage<FeedPost>(
      items: page.items.map(_view).toList(),
      nextCursor: page.nextCursor,
      source: FeedSource.trending,
    );
  }

  @override
  Future<FeedPage<FeedPost>> home({String? cursor, int limit = kFeedPageSize}) async {
    await _wait();
    final followed = _posts.where((p) => _follows.contains(p.supplierId)).toList();
    final wantFollowing = cursor == null || cursor.isEmpty ? followed.isNotEmpty : cursor.startsWith('f:');
    if (wantFollowing) {
      final page = _slice(followed, _offset(cursor, 'f'), limit, 'f', source: FeedSource.following);
      return FeedPage<FeedPost>(
        items: page.items.map(_view).toList(),
        nextCursor: page.nextCursor,
        source: FeedSource.following,
      );
    }
    return trending(cursor: cursor, limit: limit);
  }

  @override
  Future<FeedPage<FeedPost>> supplierPosts(String supplierId,
      {String? cursor, int limit = kFeedPageSize}) async {
    await _wait();
    final mine = _posts.where((p) => p.supplierId == supplierId).toList();
    final page = _slice(mine, _offset(cursor, 's'), limit, 's');
    return FeedPage<FeedPost>(
        items: page.items.map(_view).toList(), nextCursor: page.nextCursor);
  }

  @override
  Future<FeedPost> getPost(String postId) async {
    await _wait();
    return _view(_find(postId));
  }

  @override
  Future<FeedPost> createPost(PostDraft draft) async {
    await _wait();
    final sup = _supplierId();
    if (sup == null) throw _err(403, 'supplier_required');
    if (_created >= postLimit) throw _err(429, 'rate_limited', 1800);
    _created++;
    final body = draft.body.trim();
    if (body.isEmpty || body.length > kPostBodyMax) throw _err(422, 'validation_error');
    if (draft.media.length > kPostMediaMax || draft.tags.length > kPostTagsMax) {
      throw _err(422, 'validation_error');
    }
    for (final m in draft.media) {
      if (!_mediaPathRe.hasMatch(m)) throw _err(422, 'invalid_media');
    }
    if (findContactDetail(body) != null || validateTags(draft.tags) != null) {
      throw _err(422, 'content_rejected');
    }
    _postSeq++;
    final p = FeedPost(
      id: 'post_${_postSeq.toString().padLeft(3, '0')}',
      supplierId: sup,
      body: body,
      media: draft.media,
      tags: draft.tags,
      listingRef: draft.listingRef,
      createdAt: _clock().toUtc(),
    );
    _posts.insert(0, p);
    return p;
  }

  @override
  Future<void> deletePost(String postId) async {
    await _wait();
    final p = _find(postId);
    if (p.supplierId != _supplierId()) throw _err(403, 'forbidden');
    _posts.removeWhere((x) => x.id == postId);
    _comments.remove(postId);
    _liked.remove(postId);
  }

  @override
  Future<FeedPage<FollowedSupplier>> following({String? cursor, int limit = 50}) async {
    await _wait();
    final all = <FollowedSupplier>[
      for (final s in _follows) FollowedSupplier(supplierId: s),
    ];
    return _slice(all, _offset(cursor, 'w'), limit, 'w');
  }

  FollowState _followState(String s) =>
      FollowState(supplierId: s, following: _follows.contains(s), followerCount: 10 + (_follows.contains(s) ? 1 : 0));

  @override
  Future<FollowState> follow(String supplierId) async {
    await _wait();
    if (supplierId == _supplierId()) throw _err(422, 'cannot_follow_self');
    if (!_follows.contains(supplierId) && _follows.length >= 500) {
      throw _err(409, 'follow_limit_reached');
    }
    _follows.add(supplierId);
    return _followState(supplierId);
  }

  @override
  Future<FollowState> unfollow(String supplierId) async {
    await _wait();
    _follows.remove(supplierId);
    return _followState(supplierId);
  }

  @override
  Future<LikeState> like(String postId) async {
    await _wait();
    final p = _find(postId);
    if (_liked.add(postId)) _replace(p.copyWith(likeCount: p.likeCount + 1));
    return LikeState(postId: postId, liked: true, likeCount: _find(postId).likeCount);
  }

  @override
  Future<LikeState> unlike(String postId) async {
    await _wait();
    final p = _find(postId);
    if (_liked.remove(postId)) {
      _replace(p.copyWith(likeCount: p.likeCount > 0 ? p.likeCount - 1 : 0));
    }
    return LikeState(postId: postId, liked: false, likeCount: _find(postId).likeCount);
  }

  @override
  Future<FeedPage<FeedComment>> comments(String postId,
      {String? cursor, int limit = kFeedPageSize}) async {
    await _wait();
    _find(postId);
    return _slice(_comments[postId] ?? <FeedComment>[], _offset(cursor, 'c'), limit, 'c');
  }

  @override
  Future<FeedComment> addComment(String postId, String body) async {
    await _wait();
    final p = _find(postId);
    final t = body.trim();
    if (t.isEmpty || t.length > kCommentBodyMax) throw _err(422, 'validation_error');
    if (findContactDetail(t) != null) throw _err(422, 'content_rejected');
    final list = _comments.putIfAbsent(postId, () => <FeedComment>[]);
    if (list.length >= 1000) throw _err(409, 'comment_limit_reached');
    _commentSeq++;
    final c = FeedComment(
      id: 'cmt_$_commentSeq',
      postId: postId,
      userId: _userId(),
      body: t,
      createdAt: _clock().toUtc(),
    );
    list.add(c);
    _replace(p.copyWith(commentCount: list.length));
    return c;
  }

  @override
  Future<void> deleteComment(String commentId) async {
    await _wait();
    for (final entry in _comments.entries) {
      final i = entry.value.indexWhere((c) => c.id == commentId);
      if (i < 0) continue;
      final post = _find(entry.key);
      final c = entry.value[i];
      if (c.userId != _userId() && post.supplierId != _supplierId()) throw _err(403, 'forbidden');
      entry.value.removeAt(i);
      _replace(post.copyWith(commentCount: entry.value.length));
      return;
    }
    throw _err(404, 'not_found');
  }

  @override
  Future<void> reportPost(String postId, ReportReason reason, {String? details}) async {
    await _wait();
    final p = _find(postId);
    if (p.supplierId == _supplierId()) throw _err(422, 'cannot_report_own');
    _reported.add('post:$postId');
  }

  @override
  Future<void> reportComment(String commentId, ReportReason reason, {String? details}) async {
    await _wait();
    for (final list in _comments.values) {
      for (final c in list) {
        if (c.id != commentId) continue;
        if (c.userId == _userId()) throw _err(422, 'cannot_report_own');
        _reported.add('comment:$commentId');
        return;
      }
    }
    throw _err(404, 'not_found');
  }
}

final feedRepositoryProvider = Provider<FeedRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  if (!api.isMock) return LiveFeedRepository(api);
  return MockFeedRepository(
    userId: () => ref.read(authProvider)?.id ?? kMockUserId,
    supplierId: () {
      final me = ref.read(authProvider);
      return me != null && me.supplierClaimStatus == 'verified' ? me.supplierId : null;
    },
  );
});
