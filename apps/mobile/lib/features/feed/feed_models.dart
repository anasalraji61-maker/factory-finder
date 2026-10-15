/// Models for the feed service (contracts/openapi/feed.yaml). Parsing is
/// tolerant: unknown fields are ignored and missing optional ones default.

const int kPostBodyMax = 2000;
const int kCommentBodyMax = 500;
const int kPostMediaMax = 5;
const int kPostTagsMax = 5;
const int kTagMax = 30;
const int kReportDetailsMax = 300;
const int kFeedPageSize = 20;

enum FeedSource { following, trending }

/// Which list a feed controller shows.
enum FeedMode { home, trending }

DateTime? _date(Object? v) => v is String ? DateTime.tryParse(v)?.toUtc() : null;
int _count(Object? v) => v is num ? v.toInt().clamp(0, 1 << 31).toInt() : 0;

List<String> _strings(Object? v) => v is List
    ? <String>[
        for (final e in v)
          if (e != null) e.toString(),
      ]
    : const <String>[];

class FeedPost {
  const FeedPost({
    required this.id,
    required this.supplierId,
    required this.body,
    this.media = const <String>[],
    this.tags = const <String>[],
    this.listingRef,
    this.likeCount = 0,
    this.commentCount = 0,
    this.viewerLiked = false,
    this.createdAt,
  });

  final String id;
  final String supplierId;
  final String body;

  /// Server-relative (`/v1/media/files/<id>.<ext>`) or absolute URLs.
  final List<String> media;
  final List<String> tags;
  final String? listingRef;
  final int likeCount;
  final int commentCount;
  final bool viewerLiked;
  final DateTime? createdAt;

  factory FeedPost.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    final ref = m['listing_ref'];
    return FeedPost(
      id: (m['id'] ?? '').toString(),
      supplierId: (m['supplier_id'] ?? '').toString(),
      body: (m['body'] ?? '').toString(),
      media: _strings(m['media']),
      tags: _strings(m['tags']),
      listingRef: ref is String && ref.isNotEmpty ? ref : null,
      likeCount: _count(m['like_count']),
      commentCount: _count(m['comment_count']),
      viewerLiked: m['viewer_liked'] == true,
      createdAt: _date(m['created_at']),
    );
  }

  FeedPost copyWith({int? likeCount, int? commentCount, bool? viewerLiked}) => FeedPost(
        id: id,
        supplierId: supplierId,
        body: body,
        media: media,
        tags: tags,
        listingRef: listingRef,
        likeCount: likeCount ?? this.likeCount,
        commentCount: commentCount ?? this.commentCount,
        viewerLiked: viewerLiked ?? this.viewerLiked,
        createdAt: createdAt,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'supplier_id': supplierId,
        'body': body,
        'media': media,
        'tags': tags,
        'listing_ref': listingRef,
        'like_count': likeCount,
        'comment_count': commentCount,
        'viewer_liked': viewerLiked,
        if (createdAt != null) 'created_at': createdAt!.toIso8601String(),
      };
}

class FeedComment {
  const FeedComment({
    required this.id,
    required this.postId,
    required this.userId,
    required this.body,
    this.createdAt,
  });

  final String id;
  final String postId;
  final String userId;
  final String body;
  final DateTime? createdAt;

  factory FeedComment.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    return FeedComment(
      id: (m['id'] ?? '').toString(),
      postId: (m['post_id'] ?? '').toString(),
      userId: (m['user_id'] ?? '').toString(),
      body: (m['body'] ?? '').toString(),
      createdAt: _date(m['created_at']),
    );
  }
}

/// One keyset page. [source] is only set by the home / trending feeds.
class FeedPage<T> {
  const FeedPage({
    required this.items,
    this.nextCursor,
    this.source,
    this.fromCache = false,
  });

  final List<T> items;
  final String? nextCursor;
  final FeedSource? source;

  /// True when the network failed and this is the saved copy of an earlier page.
  final bool fromCache;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  static FeedPage<T> parse<T>(Object? json, T Function(Object?) item,
      {bool fromCache = false}) {
    final m = json is Map ? json : const <String, dynamic>{};
    final raw = m['items'];
    final c = m['next_cursor'];
    final s = m['source'];
    return FeedPage<T>(
      items: raw is List ? <T>[for (final e in raw) item(e)] : <T>[],
      nextCursor: c is String && c.isNotEmpty ? c : null,
      source: s == 'following'
          ? FeedSource.following
          : (s == 'trending' ? FeedSource.trending : null),
      fromCache: fromCache,
    );
  }
}

class FollowState {
  const FollowState({
    required this.supplierId,
    required this.following,
    this.followerCount = 0,
  });

  final String supplierId;
  final bool following;
  final int followerCount;

  factory FollowState.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    return FollowState(
      supplierId: (m['supplier_id'] ?? '').toString(),
      following: m['following'] == true,
      followerCount: _count(m['follower_count']),
    );
  }
}

class LikeState {
  const LikeState({required this.postId, required this.liked, required this.likeCount});

  final String postId;
  final bool liked;
  final int likeCount;

  factory LikeState.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    return LikeState(
      postId: (m['post_id'] ?? '').toString(),
      liked: m['liked'] == true,
      likeCount: _count(m['like_count']),
    );
  }
}

/// Entry of GET /v1/feed/following.
class FollowedSupplier {
  const FollowedSupplier({required this.supplierId, this.followedAt});

  final String supplierId;
  final DateTime? followedAt;

  factory FollowedSupplier.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    return FollowedSupplier(
      supplierId: (m['supplier_id'] ?? '').toString(),
      followedAt: _date(m['followed_at']),
    );
  }
}

class PostDraft {
  const PostDraft({
    required this.body,
    this.media = const <String>[],
    this.tags = const <String>[],
    this.listingRef,
  });

  final String body;
  final List<String> media;
  final List<String> tags;
  final String? listingRef;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'body': body.trim(),
        if (media.isNotEmpty) 'media': media,
        if (tags.isNotEmpty) 'tags': tags,
        if (listingRef != null && listingRef!.isNotEmpty) 'listing_ref': listingRef,
      };
}

enum ReportReason {
  prohibitedItem('prohibited_item'),
  counterfeit('counterfeit'),
  scamOrFraud('scam_or_fraud'),
  misleading('misleading'),
  contactInfo('contact_info'),
  offensive('offensive'),
  spam('spam'),
  other('other');

  const ReportReason(this.json);
  final String json;
}
