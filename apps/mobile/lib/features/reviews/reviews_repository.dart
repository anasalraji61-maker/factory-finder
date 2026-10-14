import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class ReviewsRepository {
  Future<ReviewSummary> summary(String supplierRef);

  Future<ReviewsPage> list(
    String supplierRef, {
    int page = 1,
    int pageSize = 20,
    ReviewSort sort = ReviewSort.recent,
  });

  /// [supplierRef] is only used by the mock (the server derives it from the deal).
  Future<Review> create(String dealId, ReviewDraft draft, {String? supplierRef});

  Future<Review> update(String reviewId, ReviewDraft draft);

  Future<void> delete(String reviewId);

  Future<ReviewReply> reply(String reviewId, String text);

  Future<ReviewReportResult> report(String reviewId, {String? reason, String? note});
}

class LiveReviewsRepository implements ReviewsRepository {
  LiveReviewsRepository(this._api);

  final ApiClient _api;

  static String _enc(String s) => Uri.encodeComponent(s);

  Review _review(dynamic json) {
    if (json is Map) return Review.fromJson(json);
    throw ApiException(
      status: 502,
      code: 'bad_response',
      message: 'Unexpected response from reviews service',
    );
  }

  @override
  Future<ReviewSummary> summary(String supplierRef) async => ReviewSummary.fromJson(
        await _api.get('/v1/suppliers/${_enc(supplierRef)}/review-summary'),
      );

  @override
  Future<ReviewsPage> list(
    String supplierRef, {
    int page = 1,
    int pageSize = 20,
    ReviewSort sort = ReviewSort.recent,
  }) async =>
      ReviewsPage.fromJson(
        await _api.get('/v1/suppliers/${_enc(supplierRef)}/reviews', query: {
          'page': page,
          'page_size': pageSize.clamp(1, 100).toInt(),
          'sort': sort.json,
        }),
      );

  @override
  Future<Review> create(String dealId, ReviewDraft draft, {String? supplierRef}) async =>
      _review(await _api.post('/v1/deals/${_enc(dealId)}/reviews', body: draft.toJson()));

  @override
  Future<Review> update(String reviewId, ReviewDraft draft) async =>
      _review(await _api.put('/v1/reviews/${_enc(reviewId)}', body: draft.toJson()));

  @override
  Future<void> delete(String reviewId) async {
    await _api.delete('/v1/reviews/${_enc(reviewId)}');
  }

  @override
  Future<ReviewReply> reply(String reviewId, String text) async {
    final data = await _api.post(
      '/v1/reviews/${_enc(reviewId)}/reply',
      body: {'text': text.trim()},
    );
    final json = data is Map ? data['reply'] ?? data : null;
    return ReviewReply.fromJson(json) ?? ReviewReply(text: text.trim());
  }

  @override
  Future<ReviewReportResult> report(String reviewId, {String? reason, String? note}) async {
    final n = note?.trim() ?? '';
    return ReviewReportResult.fromJson(
      await _api.post('/v1/reviews/${_enc(reviewId)}/report', body: {
        if (reason != null) 'reason': reason,
        if (n.isNotEmpty) 'note': n,
      }),
    );
  }
}

/// In-memory backend. Every supplier gets a deterministic set of seeded reviews.
class MockReviewsRepository implements ReviewsRepository {
  MockReviewsRepository({this.delayMs = 0, DateTime Function()? clock})
      : _clock = clock ?? DateTime.now;

  /// Simulated latency; 0 (default) skips timers entirely.
  final int delayMs;
  final DateTime Function() _clock;

  final Map<String, List<Review>> _bySupplier = <String, List<Review>>{};
  final Map<String, String> _dealToReview = <String, String>{};
  final Set<String> _reported = <String>{};
  int _seq = 0;

  Future<void> _wait() async {
    if (delayMs > 0) await mockDelay(delayMs);
  }

  ApiException _err(int status, String code) =>
      ApiException(status: status, code: code, message: code);

  List<Review> _all(String ref) => _bySupplier.putIfAbsent(ref, () {
        final base = DateTime.utc(2026, 9, 20);
        const names = ['Ahmed K.', 'Sara M.', 'Li W.', 'Omar H.', 'Nour A.', 'Hana B.', 'Tariq S.'];
        const ratings = [5, 5, 4, 4, 5, 3, 2];
        const titles = ['Great quality', 'Fast and clear', 'Good overall', '', 'Reliable', 'Average', 'Late delivery'];
        return <Review>[
          for (var i = 0; i < ratings.length; i++)
            Review(
              id: 'rev_${ref}_$i',
              supplierRef: ref,
              rating: ratings[i],
              subRatings: i.isEven
                  ? SubRatings(
                      quality: ratings[i].toDouble(),
                      communication: (ratings[i] - 1).clamp(1, 5).toDouble(),
                      shipping: ratings[i].toDouble(),
                    )
                  : SubRatings.empty,
              title: titles[i],
              text: i == 3 ? '' : 'Order handled professionally, samples matched the final goods.',
              reviewer: names[i],
              verifiedPurchase: i != 5,
              edited: i == 1,
              reply: i == 0
                  ? ReviewReply(
                      text: 'Thank you for your trust.',
                      createdAt: base.subtract(const Duration(days: 1)),
                    )
                  : null,
              createdAt: base.subtract(Duration(days: i * 6)),
              updatedAt: base.subtract(Duration(days: i * 6)),
            ),
        ];
      });

  ReviewSummary _summary(String ref) {
    final items = _all(ref);
    final hist = <int, int>{for (var s = 1; s <= 5; s++) s: 0};
    for (final r in items) {
      if (r.rating >= 1) hist[r.rating] = (hist[r.rating] ?? 0) + 1;
    }
    double? avgOf(String key) {
      final vals = <double>[
        for (final r in items)
          if (r.subRatings[key] != null) r.subRatings[key]!,
      ];
      if (vals.isEmpty) return null;
      return vals.reduce((a, b) => a + b) / vals.length;
    }

    return ReviewSummary(
      supplierRef: ref,
      count: items.length,
      average: averageFromHistogram(hist),
      histogram: hist,
      subRatings: SubRatings(
        quality: avgOf('quality'),
        communication: avgOf('communication'),
        shipping: avgOf('shipping'),
      ),
      completedDeals: items.length + 3,
    );
  }

  @override
  Future<ReviewSummary> summary(String supplierRef) async {
    await _wait();
    return _summary(supplierRef);
  }

  @override
  Future<ReviewsPage> list(
    String supplierRef, {
    int page = 1,
    int pageSize = 20,
    ReviewSort sort = ReviewSort.recent,
  }) async {
    await _wait();
    final items = List<Review>.of(_all(supplierRef));
    int byDate(Review a, Review b) => (b.createdAt ?? DateTime.utc(2000))
        .compareTo(a.createdAt ?? DateTime.utc(2000));
    items.sort((a, b) {
      if (sort == ReviewSort.rating && a.rating != b.rating) {
        return b.rating.compareTo(a.rating);
      }
      return byDate(a, b);
    });
    final start = (page - 1) * pageSize;
    final slice = start >= items.length
        ? <Review>[]
        : items.sublist(start, (start + pageSize).clamp(0, items.length).toInt());
    return ReviewsPage(items: slice, total: items.length, page: page, pageSize: pageSize);
  }

  void _checkContent(ReviewDraft d) {
    if (d.rating < 1 || d.rating > 5) throw _err(422, 'validation_error');
    if (d.title.length > kReviewTitleMax || d.text.length > kReviewTextMax) {
      throw _err(422, 'text_too_long');
    }
    if (findProhibited(d.title) != null || findProhibited(d.text) != null) {
      throw _err(422, 'prohibited_content');
    }
  }

  @override
  Future<Review> create(String dealId, ReviewDraft draft, {String? supplierRef}) async {
    await _wait();
    _checkContent(draft);
    if (_dealToReview.containsKey(dealId)) throw _err(409, 'review_already_exists');
    final ref = supplierRef ?? 'sup_mock';
    _seq++;
    final now = _clock().toUtc();
    final r = Review(
      id: 'rev_mine_$_seq',
      supplierRef: ref,
      rating: draft.rating,
      subRatings: draft.subRatings,
      title: draft.title.trim(),
      text: draft.text.trim(),
      reviewer: 'You',
      verifiedPurchase: true,
      mine: true,
      editableUntil: now.add(const Duration(days: 7)),
      createdAt: now,
      updatedAt: now,
    );
    _all(ref).add(r);
    _dealToReview[dealId] = r.id;
    return r;
  }

  Review? _find(String id) {
    for (final list in _bySupplier.values) {
      for (final r in list) {
        if (r.id == id) return r;
      }
    }
    return null;
  }

  void _replace(Review r) {
    final list = _bySupplier[r.supplierRef];
    if (list == null) return;
    final i = list.indexWhere((x) => x.id == r.id);
    if (i >= 0) list[i] = r;
  }

  @override
  Future<Review> update(String reviewId, ReviewDraft draft) async {
    await _wait();
    final r = _find(reviewId);
    if (r == null) throw _err(404, 'not_found');
    if (!r.mine) throw _err(403, 'forbidden');
    if (!r.isEditable(_clock().toUtc())) throw _err(409, 'review_window_closed');
    _checkContent(draft);
    final out = r.copyWith(
      rating: draft.rating,
      subRatings: draft.subRatings,
      title: draft.title.trim(),
      text: draft.text.trim(),
      edited: true,
      updatedAt: _clock().toUtc(),
    );
    _replace(out);
    return out;
  }

  @override
  Future<void> delete(String reviewId) async {
    await _wait();
    final r = _find(reviewId);
    if (r == null) throw _err(404, 'not_found');
    if (!r.mine) throw _err(403, 'forbidden');
    if (!r.isEditable(_clock().toUtc())) throw _err(409, 'review_window_closed');
    _bySupplier[r.supplierRef]?.removeWhere((x) => x.id == reviewId);
    _dealToReview.removeWhere((_, v) => v == reviewId);
  }

  @override
  Future<ReviewReply> reply(String reviewId, String text) async {
    await _wait();
    final r = _find(reviewId);
    if (r == null) throw _err(404, 'not_found');
    if (r.reply != null) throw _err(409, 'reply_already_exists');
    if (text.trim().length > kReplyTextMax) throw _err(422, 'text_too_long');
    if (findProhibited(text) != null) throw _err(422, 'prohibited_content');
    final rep = ReviewReply(text: text.trim(), createdAt: _clock().toUtc());
    _replace(r.copyWith(reply: rep));
    return rep;
  }

  @override
  Future<ReviewReportResult> report(String reviewId, {String? reason, String? note}) async {
    await _wait();
    final r = _find(reviewId);
    if (r == null) throw _err(404, 'not_found');
    final already = !_reported.add(reviewId);
    return ReviewReportResult(id: reviewId, flaggedForReview: true, alreadyReported: already);
  }
}

final reviewsRepositoryProvider = Provider<ReviewsRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockReviewsRepository() : LiveReviewsRepository(api);
});

final reviewSummaryProvider =
    FutureProvider.autoDispose.family<ReviewSummary, String>(
  (ref, supplierRef) => ref.watch(reviewsRepositoryProvider).summary(supplierRef),
);

/// The signed-in user's own review of a supplier (first `mine` of the newest
/// 100 reviews), or null.
final myReviewProvider = FutureProvider.autoDispose.family<Review?, String>(
  (ref, supplierRef) async {
    final page = await ref
        .watch(reviewsRepositoryProvider)
        .list(supplierRef, pageSize: 100);
    for (final r in page.items) {
      if (r.mine) return r;
    }
    return null;
  },
);
