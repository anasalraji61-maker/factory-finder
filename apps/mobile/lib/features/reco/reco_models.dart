import 'package:factory_finder/core/models/models.dart';

/// Currency used when a payload omits one (the app default is IQD).
const String kRecoFallbackCurrency = 'IQD';

Map<String, dynamic> _asMap(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

String _dec(Object? v, [String fallback = '0']) {
  if (v == null) return fallback;
  final s = v.toString().trim();
  return s.isEmpty ? fallback : s;
}

int _int(Object? v, [int fallback = 0]) {
  if (v is num) return v.toInt();
  return int.tryParse(v?.toString() ?? '') ?? fallback;
}

enum PriceBucket { day, week, month }

/// 365-day windows are bucketed weekly so the chart stays readable.
PriceBucket bucketForDays(int days) => days > 90 ? PriceBucket.week : PriceBucket.day;

enum PriceDirection { up, down, flat }

PriceDirection _direction(Object? v) {
  switch (v) {
    case 'up':
      return PriceDirection.up;
    case 'down':
      return PriceDirection.down;
  }
  return PriceDirection.flat;
}

class PricePoint {
  const PricePoint({
    required this.t,
    required this.avg,
    required this.min,
    required this.max,
    this.n = 1,
  });

  final DateTime t;
  final String avg;
  final String min;
  final String max;
  final int n;

  double get avgValue => double.tryParse(avg) ?? 0;

  /// Null when the timestamp cannot be parsed (the point is then skipped).
  static PricePoint? tryParse(Object? raw) {
    final j = _asMap(raw);
    final t = DateTime.tryParse(_dec(j['t'], ''));
    if (t == null) return null;
    return PricePoint(
      t: t.toUtc(),
      avg: _dec(j['avg']),
      min: _dec(j['min']),
      max: _dec(j['max']),
      n: _int(j['n'], 1),
    );
  }
}

class PriceSummary {
  const PriceSummary({
    required this.min,
    required this.max,
    required this.avg,
    required this.current,
    required this.first,
    required this.observations,
  });

  final String min;
  final String max;
  final String avg;
  final String current;
  final String first;
  final int observations;

  static PriceSummary? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final j = _asMap(raw);
    return PriceSummary(
      min: _dec(j['min']),
      max: _dec(j['max']),
      avg: _dec(j['avg']),
      current: _dec(j['current']),
      first: _dec(j['first']),
      observations: _int(j['observations']),
    );
  }
}

class PriceTrend {
  const PriceTrend({
    required this.direction,
    required this.insufficientData,
    this.changePct,
  });

  final PriceDirection direction;
  final bool insufficientData;

  /// Decimal string (first to latest observation); absent when insufficient.
  final String? changePct;

  factory PriceTrend.fromJson(Object? raw) {
    final j = _asMap(raw);
    final pct = j['change_pct'];
    return PriceTrend(
      direction: _direction(j['direction']),
      insufficientData: j['insufficient_data'] == true,
      changePct: pct == null ? null : _dec(pct, ''),
    );
  }
}

class PriceHints {
  const PriceHints({
    required this.atPeriodLow,
    required this.atPeriodHigh,
    required this.suggestedTarget,
    this.currentVsMinPct,
  });

  final bool atPeriodLow;
  final bool atPeriodHigh;
  final String? currentVsMinPct;
  final Money suggestedTarget;

  static PriceHints? tryParse(Object? raw, String fallbackCurrency) {
    if (raw is! Map) return null;
    final j = _asMap(raw);
    final target = j['suggested_target'];
    if (target is! Map) return null;
    final m = _asMap(target);
    return PriceHints(
      atPeriodLow: j['at_period_low'] == true,
      atPeriodHigh: j['at_period_high'] == true,
      currentVsMinPct: j['current_vs_min_pct']?.toString(),
      suggestedTarget: Money(
        amount: _dec(m['amount']),
        currency: (m['currency'] as String?) ?? fallbackCurrency,
      ),
    );
  }
}

class PriceHistory {
  const PriceHistory({
    required this.listingId,
    required this.currency,
    required this.days,
    required this.bucket,
    required this.synthetic,
    required this.points,
    required this.trend,
    this.unit,
    this.summary,
    this.hints,
  });

  final String listingId;
  final String currency;
  final String? unit;
  final int days;
  final PriceBucket bucket;

  /// True for the deterministic mock series: label it as an estimate.
  final bool synthetic;
  final List<PricePoint> points;
  final PriceSummary? summary;
  final PriceTrend trend;
  final PriceHints? hints;

  /// A chart and trend need at least two points and no server-side flag.
  bool get hasEnoughData => !trend.insufficientData && points.length >= 2;

  factory PriceHistory.fromJson(Map<String, dynamic> j) {
    final currency = (j['currency'] as String?) ?? kRecoFallbackCurrency;
    final bucketRaw = j['bucket'];
    return PriceHistory(
      listingId: _dec(j['listing_id'], ''),
      currency: currency,
      unit: j['unit'] as String?,
      days: _int(j['days'], 90),
      bucket: PriceBucket.values.firstWhere(
        (b) => b.name == bucketRaw,
        orElse: () => PriceBucket.day,
      ),
      synthetic: j['synthetic'] == true,
      points: [
        for (final p in (j['points'] as List?) ?? const [])
          if (PricePoint.tryParse(p) != null) PricePoint.tryParse(p)!,
      ],
      summary: PriceSummary.tryParse(j['summary']),
      trend: PriceTrend.fromJson(j['trend']),
      hints: PriceHints.tryParse(j['hints'], currency),
    );
  }
}

class RecoReason {
  const RecoReason({
    required this.code,
    required this.en,
    required this.ar,
    this.refListingId,
  });

  final String code;
  final String en;
  final String ar;
  final String? refListingId;

  /// Arabic for `ar`, English otherwise; falls back to the other language
  /// then the code when a text is empty.
  String text(String languageCode) {
    final primary = languageCode == 'ar' ? ar : en;
    if (primary.isNotEmpty) return primary;
    final other = languageCode == 'ar' ? en : ar;
    return other.isNotEmpty ? other : code;
  }

  factory RecoReason.fromJson(Map<String, dynamic> j) => RecoReason(
        code: _dec(j['code'], ''),
        en: (j['en'] as String?) ?? '',
        ar: (j['ar'] as String?) ?? '',
        refListingId: j['ref_listing_id'] as String?,
      );
}

class RecoItem {
  const RecoItem({required this.listing, this.score = 0, this.reasons = const []});

  final Listing listing;
  final double score;
  final List<RecoReason> reasons;

  factory RecoItem.fromJson(Map<String, dynamic> j) => RecoItem(
        listing: Listing.fromJson(_asMap(j['listing'])),
        score: (j['score'] is num) ? (j['score'] as num).toDouble() : 0,
        reasons: [
          for (final r in (j['reasons'] as List?) ?? const [])
            if (r is Map) RecoReason.fromJson(Map<String, dynamic>.from(r)),
        ],
      );
}

/// Items of GET /listings/{id}/similar or GET /recommendations.
class RecoPage {
  const RecoPage({
    this.items = const [],
    this.total = 0,
    this.basedOn = const [],
    this.listingId,
    this.warning,
  });

  final List<RecoItem> items;
  final int total;

  /// Only for recommendations: reference ids that resolved to listings.
  final List<String> basedOn;

  /// Only for similar: the listing the items are similar to.
  final String? listingId;

  /// Backend `warning` (e.g. `partial_results: ...` when the time budget ran out).
  final String? warning;

  /// True when the server flagged the page as incomplete.
  bool get isPartial => warning != null && warning!.startsWith('partial_results');

  factory RecoPage.fromJson(Map<String, dynamic> j) {
    final items = [
      for (final e in (j['items'] as List?) ?? const [])
        if (e is Map) RecoItem.fromJson(Map<String, dynamic>.from(e)),
    ];
    return RecoPage(
      items: items,
      total: _int(j['total'], items.length),
      basedOn: [
        for (final e in (j['based_on'] as List?) ?? const []) e.toString(),
      ],
      listingId: j['listing_id'] as String?,
      warning: j['warning'] is String ? j['warning'] as String : null,
    );
  }
}
