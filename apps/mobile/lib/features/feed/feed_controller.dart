import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Canonical copy of every post seen. Lists hold ids only, so a like or a
/// comment count change shows everywhere (feed, supplier posts, detail).
class PostStore extends StateNotifier<Map<String, FeedPost>> {
  PostStore() : super(const <String, FeedPost>{});

  void putAll(Iterable<FeedPost> posts) {
    final next = Map<String, FeedPost>.of(state);
    for (final p in posts) {
      if (p.id.isNotEmpty) next[p.id] = p;
    }
    state = next;
  }

  void update(String id, FeedPost Function(FeedPost) change) {
    final current = state[id];
    if (current == null) return;
    state = <String, FeedPost>{...state, id: change(current)};
  }

  void remove(String id) {
    if (!state.containsKey(id)) return;
    state = Map<String, FeedPost>.of(state)..remove(id);
  }
}

final feedPostStoreProvider =
    StateNotifierProvider<PostStore, Map<String, FeedPost>>((ref) => PostStore());

final feedPostProvider = Provider.family<FeedPost?, String>(
  (ref, id) => ref.watch(feedPostStoreProvider.select((m) => m[id])),
);

class FeedListState {
  const FeedListState({
    this.ids = const <String>[],
    this.nextCursor,
    this.loading = true,
    this.loadingMore = false,
    this.error,
    this.moreError,
    this.source,
  });

  final List<String> ids;
  final String? nextCursor;

  /// True while the first page (or a pull-to-refresh with nothing shown) loads.
  final bool loading;
  final bool loadingMore;
  final Object? error;
  final Object? moreError;
  final FeedSource? source;

  bool get hasMore => nextCursor != null;

  FeedListState copyWith({
    List<String>? ids,
    Object? nextCursor = _keep,
    bool? loading,
    bool? loadingMore,
    Object? error = _keep,
    Object? moreError = _keep,
    Object? source = _keep,
  }) =>
      FeedListState(
        ids: ids ?? this.ids,
        nextCursor: identical(nextCursor, _keep) ? this.nextCursor : nextCursor as String?,
        loading: loading ?? this.loading,
        loadingMore: loadingMore ?? this.loadingMore,
        error: identical(error, _keep) ? this.error : error,
        moreError: identical(moreError, _keep) ? this.moreError : moreError,
        source: identical(source, _keep) ? this.source : source as FeedSource?,
      );
}

const Object _keep = Object();

typedef FeedFetch = Future<FeedPage<FeedPost>> Function(String? cursor);

/// Keyset-paginated list of posts: first page, refresh, load more.
class FeedListController extends StateNotifier<FeedListState> {
  FeedListController(this._store, this._fetch) : super(const FeedListState()) {
    refresh();
  }

  final PostStore _store;
  final FeedFetch _fetch;
  int _generation = 0;

  /// Reloads the first page. Items already shown stay visible meanwhile.
  Future<void> refresh() async {
    final gen = ++_generation;
    if (state.ids.isEmpty) {
      state = state.copyWith(loading: true, error: null, loadingMore: false);
    } else {
      state = state.copyWith(error: null, moreError: null, loadingMore: false);
    }
    try {
      final page = await _fetch(null);
      if (!mounted || gen != _generation) return;
      _store.putAll(page.items);
      state = FeedListState(
        ids: _dedupe(page.items.map((p) => p.id)),
        nextCursor: page.nextCursor,
        loading: false,
        source: page.source,
      );
    } catch (e) {
      if (!mounted || gen != _generation) return;
      state = state.copyWith(loading: false, error: e);
    }
  }

  Future<void> loadMore() async {
    final cursor = state.nextCursor;
    if (cursor == null || state.loadingMore || state.loading) return;
    final gen = _generation;
    state = state.copyWith(loadingMore: true, moreError: null);
    try {
      final page = await _fetch(cursor);
      if (!mounted || gen != _generation) return;
      _store.putAll(page.items);
      state = state.copyWith(
        ids: _dedupe(<String>[...state.ids, ...page.items.map((p) => p.id)]),
        nextCursor: page.nextCursor,
        loadingMore: false,
      );
    } catch (e) {
      if (!mounted || gen != _generation) return;
      state = state.copyWith(loadingMore: false, moreError: e);
    }
  }

  void removeId(String id) {
    if (!state.ids.contains(id)) return;
    state = state.copyWith(ids: state.ids.where((x) => x != id).toList());
  }

  /// Puts a freshly published post first (supplier lists).
  void prepend(String id) {
    if (state.ids.contains(id)) return;
    state = state.copyWith(ids: <String>[id, ...state.ids]);
  }

  static List<String> _dedupe(Iterable<String> ids) {
    final seen = <String>{};
    return <String>[
      for (final id in ids)
        if (seen.add(id)) id,
    ];
  }
}

/// Family key: `home`, `trending` or `sup:<supplier id>`.
final feedListProvider =
    StateNotifierProvider.autoDispose.family<FeedListController, FeedListState, String>(
  (ref, key) {
    final repo = ref.watch(feedRepositoryProvider);
    final store = ref.read(feedPostStoreProvider.notifier);
    FeedFetch fetch;
    if (key == 'home') {
      fetch = (c) => repo.home(cursor: c);
    } else if (key == 'trending') {
      fetch = (c) => repo.trending(cursor: c);
    } else {
      final sid = key.startsWith('sup:') ? key.substring(4) : key;
      fetch = (c) => repo.supplierPosts(sid, cursor: c);
    }
    return FeedListController(store, fetch);
  },
);

/// One post fetched on its own (deep link / detail), stored in [PostStore].
final feedPostDetailProvider = FutureProvider.autoDispose.family<FeedPost, String>(
  (ref, id) async {
    final post = await ref.watch(feedRepositoryProvider).getPost(id);
    ref.read(feedPostStoreProvider.notifier).putAll(<FeedPost>[post]);
    return post;
  },
);

// -- comments -------------------------------------------------------------

class CommentsState {
  const CommentsState({
    this.items = const <FeedComment>[],
    this.nextCursor,
    this.loading = true,
    this.loadingMore = false,
    this.error,
    this.moreError,
  });

  final List<FeedComment> items;
  final String? nextCursor;
  final bool loading;
  final bool loadingMore;
  final Object? error;
  final Object? moreError;

  bool get hasMore => nextCursor != null;
}

class CommentsController extends StateNotifier<CommentsState> {
  CommentsController(this._repo, this._store, this.postId) : super(const CommentsState()) {
    refresh();
  }

  final FeedRepository _repo;
  final PostStore _store;
  final String postId;

  Future<void> refresh() async {
    state = CommentsState(items: state.items, loading: state.items.isEmpty);
    try {
      final page = await _repo.comments(postId);
      if (!mounted) return;
      state = CommentsState(items: page.items, nextCursor: page.nextCursor, loading: false);
    } catch (e) {
      if (!mounted) return;
      state = CommentsState(items: state.items, loading: false, error: e);
    }
  }

  Future<void> loadMore() async {
    final cursor = state.nextCursor;
    if (cursor == null || state.loadingMore || state.loading) return;
    state = CommentsState(
      items: state.items,
      nextCursor: cursor,
      loading: false,
      loadingMore: true,
    );
    try {
      final page = await _repo.comments(postId, cursor: cursor);
      if (!mounted) return;
      final seen = state.items.map((c) => c.id).toSet();
      state = CommentsState(
        items: <FeedComment>[
          ...state.items,
          for (final c in page.items)
            if (seen.add(c.id)) c,
        ],
        nextCursor: page.nextCursor,
        loading: false,
      );
    } catch (e) {
      if (!mounted) return;
      state = CommentsState(
        items: state.items,
        nextCursor: cursor,
        loading: false,
        moreError: e,
      );
    }
  }

  /// Throws the repository's error so the caller can show it.
  Future<void> add(String body) async {
    final c = await _repo.addComment(postId, body);
    if (!mounted) return;
    state = CommentsState(
      items: <FeedComment>[...state.items, c],
      nextCursor: state.nextCursor,
      loading: false,
    );
    _store.update(postId, (p) => p.copyWith(commentCount: p.commentCount + 1));
  }

  Future<void> delete(String commentId) async {
    await _repo.deleteComment(commentId);
    if (!mounted) return;
    state = CommentsState(
      items: state.items.where((c) => c.id != commentId).toList(),
      nextCursor: state.nextCursor,
      loading: false,
    );
    _store.update(
      postId,
      (p) => p.copyWith(commentCount: p.commentCount > 0 ? p.commentCount - 1 : 0),
    );
  }
}

final feedCommentsProvider =
    StateNotifierProvider.autoDispose.family<CommentsController, CommentsState, String>(
  (ref, postId) => CommentsController(
    ref.watch(feedRepositoryProvider),
    ref.read(feedPostStoreProvider.notifier),
    postId,
  ),
);

// -- following ------------------------------------------------------------

class FollowingState {
  const FollowingState({
    this.ids = const <String>{},
    this.loaded = false,
    this.error,
    this.busy = const <String>{},
  });

  final Set<String> ids;
  final bool loaded;
  final Object? error;

  /// Suppliers with a follow / unfollow request in flight.
  final Set<String> busy;

  bool isFollowing(String supplierId) => ids.contains(supplierId);
}

class FollowingController extends StateNotifier<FollowingState> {
  FollowingController(this._repo, {this.onChanged, bool autoLoad = true})
      : super(const FollowingState()) {
    if (autoLoad) load();
  }

  final FeedRepository _repo;
  final void Function()? onChanged;

  /// Reads every page of GET /v1/feed/following (the cap is 500 follows).
  Future<void> load() async {
    try {
      final ids = <String>{};
      String? cursor;
      for (var i = 0; i < 12; i++) {
        final page = await _repo.following(cursor: cursor, limit: 50);
        ids.addAll(page.items.map((f) => f.supplierId));
        cursor = page.nextCursor;
        if (cursor == null) break;
      }
      if (!mounted) return;
      state = FollowingState(ids: ids, loaded: true, busy: state.busy);
    } catch (e) {
      if (!mounted) return;
      state = FollowingState(ids: state.ids, loaded: true, error: e, busy: state.busy);
    }
  }

  /// Optimistic follow / unfollow; restores the previous state and rethrows on
  /// failure. Concurrent taps on the same supplier are ignored.
  Future<void> toggle(String supplierId) async {
    if (state.busy.contains(supplierId)) return;
    final was = state.ids.contains(supplierId);
    _set(supplierId, !was, busy: true);
    try {
      final s = was ? await _repo.unfollow(supplierId) : await _repo.follow(supplierId);
      if (!mounted) return;
      _set(supplierId, s.following, busy: false);
      onChanged?.call();
    } catch (_) {
      if (mounted) _set(supplierId, was, busy: false);
      rethrow;
    }
  }

  void _set(String id, bool following, {required bool busy}) {
    final ids = Set<String>.of(state.ids);
    following ? ids.add(id) : ids.remove(id);
    final b = Set<String>.of(state.busy);
    busy ? b.add(id) : b.remove(id);
    state = FollowingState(ids: ids, loaded: state.loaded, error: state.error, busy: b);
  }
}

final followingProvider = StateNotifierProvider<FollowingController, FollowingState>(
  (ref) => FollowingController(
    ref.watch(feedRepositoryProvider),
    // The home feed depends on who is followed.
    onChanged: () => ref.invalidate(feedListProvider('home')),
    autoLoad: ref.watch(authProvider) != null,
  ),
);

// -- actions --------------------------------------------------------------

class FeedActions {
  FeedActions(this._ref);

  final Ref _ref;
  final Set<String> _liking = <String>{};

  FeedRepository get _repo => _ref.read(feedRepositoryProvider);
  PostStore get _store => _ref.read(feedPostStoreProvider.notifier);

  /// Optimistic like / unlike. On failure the post is restored to what it was
  /// before the tap and the error is rethrown. Taps while a request for the
  /// same post is in flight are ignored.
  Future<void> toggleLike(String postId) async {
    final before = _ref.read(feedPostStoreProvider)[postId];
    if (before == null || !_liking.add(postId)) return;
    final want = !before.viewerLiked;
    _store.update(
      postId,
      (p) => p.copyWith(
        viewerLiked: want,
        likeCount: want ? p.likeCount + 1 : (p.likeCount > 0 ? p.likeCount - 1 : 0),
      ),
    );
    try {
      final s = want ? await _repo.like(postId) : await _repo.unlike(postId);
      _store.update(postId, (p) => p.copyWith(viewerLiked: s.liked, likeCount: s.likeCount));
    } catch (_) {
      _store.update(
        postId,
        (p) => p.copyWith(viewerLiked: before.viewerLiked, likeCount: before.likeCount),
      );
      rethrow;
    } finally {
      _liking.remove(postId);
    }
  }

  Future<void> deletePost(String postId) async {
    await _repo.deletePost(postId);
    _store.remove(postId);
    _ref.invalidate(feedListProvider);
  }

  Future<FeedPost> publish(PostDraft draft) async {
    final post = await _repo.createPost(draft);
    _store.putAll(<FeedPost>[post]);
    _ref.invalidate(feedListProvider);
    return post;
  }

  Future<void> reportPost(String postId, ReportReason reason, String? details) =>
      _repo.reportPost(postId, reason, details: details);

  Future<void> reportComment(String commentId, ReportReason reason, String? details) =>
      _repo.reportComment(commentId, reason, details: details);
}

final feedActionsProvider = Provider<FeedActions>((ref) => FeedActions(ref));
