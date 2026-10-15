import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';

/// Sub-rating keys in display order.
const List<String> kSubRatingKeys = <String>['quality', 'communication', 'shipping'];

/// Report reasons accepted by the server.
const List<String> kReportReasons = <String>['spam', 'abuse', 'fake', 'other'];

const int kReviewTitleMax = 80;
const int kReviewTextMax = 1000;
const int kReplyTextMax = 500;

enum ReviewSort {
  recent,
  rating;

  String get json => name;
}

double? _toDouble(dynamic v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v.trim());
  return null;
}

int? _toInt(dynamic v) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v.trim());
  return null;
}

DateTime? _toDate(dynamic v) => v is String ? DateTime.tryParse(v) : null;

Map<String, dynamic> _asMap(dynamic v) =>
    v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

/// Quality / communication / shipping values (null = not rated).
class SubRatings {
  const SubRatings({this.quality, this.communication, this.shipping});

  final double? quality;
  final double? communication;
  final double? shipping;

  static const SubRatings empty = SubRatings();

  factory SubRatings.fromJson(dynamic json) {
    final j = _asMap(json);
    return SubRatings(
      quality: _toDouble(j['quality']),
      communication: _toDouble(j['communication']),
      shipping: _toDouble(j['shipping']),
    );
  }

  double? operator [](String key) {
    switch (key) {
      case 'quality':
        return quality;
      case 'communication':
        return communication;
      case 'shipping':
        return shipping;
    }
    return null;
  }

  bool get isEmpty => quality == null && communication == null && shipping == null;

  SubRatings withValue(String key, double? value) => SubRatings(
        quality: key == 'quality' ? value : quality,
        communication: key == 'communication' ? value : communication,
        shipping: key == 'shipping' ? value : shipping,
      );

  /// Whole-star body for POST/PUT; unrated keys are omitted.
  Map<String, int> toJson() {
    final out = <String, int>{};
    for (final k in kSubRatingKeys) {
      final v = this[k];
      if (v != null) out[k] = v.round().clamp(1, 5).toInt();
    }
    return out;
  }
}

class ReviewSummary {
  const ReviewSummary({
    required this.supplierRef,
    this.count = 0,
    this.average,
    this.histogram = const <int, int>{},
    this.subRatings = SubRatings.empty,
    this.completedDeals = 0,
  });

  final String supplierRef;
  final int count;
  final double? average;

  /// Star (1..5) -> number of reviews.
  final Map<int, int> histogram;
  final SubRatings subRatings;
  final int completedDeals;

  bool get hasReviews => count > 0;

  /// Server average, else derived from the histogram.
  double? get displayAverage => average ?? averageFromHistogram(histogram);

  factory ReviewSummary.fromJson(dynamic json) {
    final j = _asMap(json);
    final hist = <int, int>{};
    _asMap(j['histogram']).forEach((k, v) {
      final star = int.tryParse(k);
      final n = _toInt(v);
      if (star != null && n != null && star >= 1 && star <= 5) hist[star] = n;
    });
    return ReviewSummary(
      supplierRef: (j['supplier_ref'] ?? '').toString(),
      count: _toInt(j['count']) ?? histogramTotal(hist),
      average: _toDouble(j['average']),
      histogram: hist,
      subRatings: SubRatings.fromJson(j['sub_ratings']),
      completedDeals: _toInt(j['completed_deals']) ?? 0,
    );
  }
}

/// Sum of all histogram buckets.
int histogramTotal(Map<int, int> h) {
  var t = 0;
  for (var s = 1; s <= 5; s++) {
    t += h[s] ?? 0;
  }
  return t;
}

/// Share (0..1) of reviews with [star] stars; 0 when there are none.
double histogramShare(Map<int, int> h, int star) {
  final total = histogramTotal(h);
  if (total == 0) return 0;
  return (h[star] ?? 0) / total;
}

/// Mean star value of the histogram, null when empty.
double? averageFromHistogram(Map<int, int> h) {
  final total = histogramTotal(h);
  if (total == 0) return null;
  var sum = 0;
  for (var s = 1; s <= 5; s++) {
    sum += s * (h[s] ?? 0);
  }
  return sum / total;
}

class ReviewReply {
  const ReviewReply({required this.text, this.createdAt});

  final String text;
  final DateTime? createdAt;

  static ReviewReply? fromJson(dynamic json) {
    if (json is! Map) return null;
    final j = _asMap(json);
    final text = (j['text'] ?? '').toString();
    if (text.isEmpty) return null;
    return ReviewReply(text: text, createdAt: _toDate(j['created_at']));
  }
}

class Review {
  const Review({
    required this.id,
    required this.supplierRef,
    required this.rating,
    this.subRatings = SubRatings.empty,
    this.title = '',
    this.text = '',
    this.reviewer = '',
    this.verifiedPurchase = false,
    this.edited = false,
    this.reply,
    this.mine = false,
    this.editableUntil,
    this.flaggedForReview = false,
    this.createdAt,
    this.updatedAt,
  });

  final String id;
  final String supplierRef;
  final int rating;
  final SubRatings subRatings;
  final String title;
  final String text;
  final String reviewer;
  final bool verifiedPurchase;
  final bool edited;
  final ReviewReply? reply;
  final bool mine;
  final DateTime? editableUntil;
  final bool flaggedForReview;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  factory Review.fromJson(dynamic json) {
    final j = _asMap(json);
    return Review(
      id: (j['id'] ?? '').toString(),
      supplierRef: (j['supplier_ref'] ?? '').toString(),
      rating: (_toInt(j['rating']) ?? 0).clamp(0, 5).toInt(),
      subRatings: SubRatings.fromJson(j['sub_ratings']),
      title: (j['title'] ?? '').toString(),
      text: (j['text'] ?? '').toString(),
      reviewer: (j['reviewer'] ?? '').toString(),
      verifiedPurchase: j['verified_purchase'] == true,
      edited: j['edited'] == true,
      reply: ReviewReply.fromJson(j['reply']),
      mine: j['mine'] == true,
      editableUntil: _toDate(j['editable_until']),
      flaggedForReview: j['flagged_for_review'] == true,
      createdAt: _toDate(j['created_at']),
      updatedAt: _toDate(j['updated_at']),
    );
  }

  /// Own review that can still be edited or deleted at [now].
  bool isEditable(DateTime now) {
    if (!mine) return false;
    final until = editableUntil;
    return until == null || now.isBefore(until);
  }

  Review copyWith({
    int? rating,
    SubRatings? subRatings,
    String? title,
    String? text,
    bool? edited,
    ReviewReply? reply,
    bool? flaggedForReview,
    DateTime? updatedAt,
  }) =>
      Review(
        id: id,
        supplierRef: supplierRef,
        rating: rating ?? this.rating,
        subRatings: subRatings ?? this.subRatings,
        title: title ?? this.title,
        text: text ?? this.text,
        reviewer: reviewer,
        verifiedPurchase: verifiedPurchase,
        edited: edited ?? this.edited,
        reply: reply ?? this.reply,
        mine: mine,
        editableUntil: editableUntil,
        flaggedForReview: flaggedForReview ?? this.flaggedForReview,
        createdAt: createdAt,
        updatedAt: updatedAt ?? this.updatedAt,
      );
}

class ReviewsPage {
  const ReviewsPage({
    this.items = const <Review>[],
    this.total = 0,
    this.page = 1,
    this.pageSize = 20,
  });

  final List<Review> items;
  final int total;
  final int page;
  final int pageSize;

  factory ReviewsPage.fromJson(dynamic json) {
    final j = _asMap(json);
    final raw = j['items'];
    final items = <Review>[
      if (raw is List)
        for (final e in raw)
          if (e is Map) Review.fromJson(e),
    ];
    return ReviewsPage(
      items: items,
      total: _toInt(j['total']) ?? items.length,
      page: _toInt(j['page']) ?? 1,
      pageSize: _toInt(j['page_size']) ?? 20,
    );
  }
}

class ReviewReportResult {
  const ReviewReportResult({
    required this.id,
    this.flaggedForReview = false,
    this.alreadyReported = false,
  });

  final String id;
  final bool flaggedForReview;
  final bool alreadyReported;

  factory ReviewReportResult.fromJson(dynamic json) {
    final j = _asMap(json);
    return ReviewReportResult(
      id: (j['id'] ?? '').toString(),
      flaggedForReview: j['flagged_for_review'] == true,
      alreadyReported: j['already_reported'] == true,
    );
  }
}

/// Body of POST /v1/deals/{id}/reviews and PUT /v1/reviews/{id}.
class ReviewDraft {
  const ReviewDraft({
    required this.rating,
    this.title = '',
    this.text = '',
    this.subRatings = SubRatings.empty,
  });

  final int rating;
  final String title;
  final String text;
  final SubRatings subRatings;

  Map<String, dynamic> toJson() {
    final t = title.trim();
    final x = text.trim();
    final sub = subRatings.toJson();
    return <String, dynamic>{
      'rating': rating,
      if (t.isNotEmpty) 'title': t,
      if (x.isNotEmpty) 'text': x,
      if (sub.isNotEmpty) 'sub_ratings': sub,
    };
  }
}

// ---------------------------------------------------------------------------
// Client-side validation (mirrors the server's prohibited-content rules).
// ---------------------------------------------------------------------------

enum ProhibitedKind { url, email, phone }

final RegExp _emailRe = RegExp(r'[\w.+\-]+@[\w\-]+\.[\w.\-]+');
final RegExp _urlRe = RegExp(
  r'(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9\-]*\.(?:com|net|org|info|biz|io|co|cn|ru|me|app|shop|store|xyz)\b',
  caseSensitive: false,
);
final RegExp _phoneRe = RegExp(r'(?:\+|00)?\d(?:[\s\-().]?\d){6,}');

/// First kind of contact detail found in [text], or null.
ProhibitedKind? findProhibited(String text) {
  if (_emailRe.hasMatch(text)) return ProhibitedKind.email;
  if (_urlRe.hasMatch(text)) return ProhibitedKind.url;
  if (_phoneRe.hasMatch(text)) return ProhibitedKind.phone;
  return null;
}

class ReviewValidation {
  const ReviewValidation({this.ratingKey, this.titleKey, this.textKey});

  /// i18n keys of the first problem per field, null when fine.
  final String? ratingKey;
  final String? titleKey;
  final String? textKey;

  bool get ok => ratingKey == null && titleKey == null && textKey == null;
}

String? _fieldError(String value, int max) {
  if (value.length > max) return 'reviews.err.text_too_long';
  final kind = findProhibited(value);
  if (kind == null) return null;
  return 'reviews.err.prohibited.${kind.name}';
}

ReviewValidation validateReview({
  required int rating,
  required String title,
  required String text,
}) {
  return ReviewValidation(
    ratingKey: (rating < 1 || rating > 5) ? 'reviews.err.rating' : null,
    titleKey: _fieldError(title.trim(), kReviewTitleMax),
    textKey: _fieldError(text.trim(), kReviewTextMax),
  );
}

/// Reply text check: non-empty, <= 500 chars, no contact details.
String? validateReply(String text) {
  final t = text.trim();
  if (t.isEmpty) return 'reviews.err.reply_empty';
  return _fieldError(t, kReplyTextMax);
}

/// i18n key for any failure of the reviews API.
String reviewErrorKey(Object e) {
  if (e is! ApiException) return 'reviews.err.generic';
  switch (e.code) {
    case 'deal_not_reviewable':
    case 'review_already_exists':
    case 'supplier_unverified':
    case 'review_window_closed':
    case 'reply_already_exists':
    case 'text_too_long':
    case 'rate_limited':
    case 'validation_error':
      return 'reviews.err.${e.code}';
    case 'prohibited_content':
      return 'reviews.err.prohibited';
    case 'timeout':
    case 'network_error':
      return 'reviews.err.network';
  }
  final shared = apiErrorKey(e);
  if (shared != null) return shared;
  switch (e.status) {
    case 401:
      return 'reviews.err.auth';
    case 403:
      return 'reviews.err.forbidden';
    case 404:
      return 'reviews.err.not_found';
    case 409:
      return 'reviews.err.conflict';
    case 422:
      return 'reviews.err.validation_error';
    case 429:
      return 'reviews.err.rate_limited';
  }
  return 'reviews.err.generic';
}
