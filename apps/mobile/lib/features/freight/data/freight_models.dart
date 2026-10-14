import 'package:factory_finder/features/freight/data/freight_decimal.dart';

const List<String> kFreightModes = ['sea', 'air', 'road', 'rail'];
const List<String> kFreightIncoterms = [
  'EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP', //
];
const List<String> kContainerTypes = [
  '20GP', '40GP', '40HC', '45HC', '20RF', '40RF', '20OT', '40OT', '20FR', '40FR', 'LCL', //
];
const List<String> kReportReasons = [
  'prohibited_item', 'counterfeit', 'scam_or_fraud', 'misleading', //
  'contact_info', 'offensive', 'spam', 'other',
];
const List<String> kQuoteSorts = ['score', 'price', 'transit', 'rating'];
const List<String> kRequestStatuses = ['open', 'awarded', 'closed', 'expired'];

/// Countries offered in pickers (ISO alpha-2). Lanes may also use `*`.
const List<String> kFreightCountries = [
  'CN', 'IQ', 'TR', 'AE', 'SA', 'DE', 'IT', 'US', 'IN', 'EG', 'JO', 'KW', //
];

Map<String, dynamic> _m(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
String _s(Object? v, [String d = '']) => v == null ? d : v.toString();
String? _sn(Object? v) => v == null ? null : v.toString();
int _i(Object? v, [int d = 0]) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse('$v') ?? d;
}

double _d(Object? v, [double d = 0]) {
  if (v is num) return v.toDouble();
  return double.tryParse('$v') ?? d;
}

DateTime? _dt(Object? v) => v is String ? DateTime.tryParse(v) : null;
List<String> _sl(Object? v) =>
    v is List ? [for (final e in v) e.toString()] : const <String>[];
List<Map<String, dynamic>> _ml(Object? v) =>
    v is List ? [for (final e in v) if (e is Map) _m(e)] : const [];

/// Keyset page (`items` + opaque `next_cursor`).
class FreightPage<T> {
  const FreightPage({required this.items, this.nextCursor});

  final List<T> items;
  final String? nextCursor;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  static FreightPage<T> fromJson<T>(
    Object? json,
    T Function(Map<String, dynamic>) item,
  ) {
    final j = _m(json);
    return FreightPage<T>(
      items: [for (final e in _ml(j['items'])) item(e)],
      nextCursor: _sn(j['next_cursor']),
    );
  }
}

class Lane {
  const Lane({required this.origin, required this.destination});

  /// ISO alpha-2 or `*` (any country).
  final String origin;
  final String destination;

  factory Lane.fromJson(Map<String, dynamic> j) => Lane(
        origin: _s(j['origin_country'], '*'),
        destination: _s(j['destination_country'], '*'),
      );

  Map<String, dynamic> toJson() =>
      {'origin_country': origin, 'destination_country': destination};

  @override
  bool operator ==(Object other) =>
      other is Lane && other.origin == origin && other.destination == destination;

  @override
  int get hashCode => Object.hash(origin, destination);
}

class FreightRating {
  const FreightRating({this.average, this.count = 0});

  /// Mean stars, 2 decimals; null until rated.
  final String? average;
  final int count;

  factory FreightRating.fromJson(Object? json) {
    final j = _m(json);
    return FreightRating(average: _sn(j['average']), count: _i(j['count']));
  }
}

class ForwarderSummary {
  const ForwarderSummary({
    required this.id,
    required this.companyName,
    required this.countryCode,
    this.rating = const FreightRating(),
    this.completedJobs = 0,
  });

  final String id;
  final String companyName;
  final String countryCode;
  final FreightRating rating;
  final int completedJobs;

  factory ForwarderSummary.fromJson(Map<String, dynamic> j) => ForwarderSummary(
        id: _s(j['id']),
        companyName: _s(j['company_name']),
        countryCode: _s(j['country_code']),
        rating: FreightRating.fromJson(j['rating']),
        completedJobs: _i(j['completed_jobs']),
      );
}

class Forwarder {
  const Forwarder({
    required this.id,
    required this.companyName,
    required this.countryCode,
    this.description,
    this.lanes = const [],
    this.modes = const [],
    this.incoterms = const [],
    this.certifications = const [],
    this.rating = const FreightRating(),
    this.completedJobs = 0,
    this.status,
  });

  final String id;
  final String companyName;
  final String countryCode;
  final String? description;
  final List<Lane> lanes;
  final List<String> modes;
  final List<String> incoterms;
  final List<String> certifications;
  final FreightRating rating;
  final int completedJobs;

  /// `active` / `suspended`; only present on the owner's own profile.
  final String? status;

  factory Forwarder.fromJson(Map<String, dynamic> j) => Forwarder(
        id: _s(j['id']),
        companyName: _s(j['company_name']),
        countryCode: _s(j['country_code']),
        description: _sn(j['description']),
        lanes: [for (final l in _ml(j['lanes'])) Lane.fromJson(l)],
        modes: _sl(j['modes']),
        incoterms: _sl(j['incoterms']),
        certifications: _sl(j['certifications']),
        rating: FreightRating.fromJson(j['rating']),
        completedJobs: _i(j['completed_jobs']),
        status: _sn(j['status']),
      );
}

class Whoami {
  const Whoami({required this.userId, this.forwarderId, this.forwarderStatus});

  final String userId;
  final String? forwarderId;

  /// null (not a forwarder), `active` or `suspended`.
  final String? forwarderStatus;

  bool get isActive => forwarderStatus == 'active';
  bool get isSuspended => forwarderStatus == 'suspended';

  factory Whoami.fromJson(Object? json) {
    final j = _m(json);
    return Whoami(
      userId: _s(j['user_id']),
      forwarderId: _sn(j['forwarder_id']),
      forwarderStatus: _sn(j['forwarder_status']),
    );
  }
}

class FreightApplication {
  const FreightApplication({
    required this.id,
    required this.companyName,
    required this.countryCode,
    this.description,
    this.lanes = const [],
    this.modes = const [],
    this.incoterms = const [],
    this.certifications = const [],
    required this.status,
    this.reviewNote,
    this.forwarderId,
    this.createdAt,
    this.reviewedAt,
  });

  final String id;
  final String companyName;
  final String countryCode;
  final String? description;
  final List<Lane> lanes;
  final List<String> modes;
  final List<String> incoterms;
  final List<String> certifications;

  /// pending | approved | rejected
  final String status;
  final String? reviewNote;
  final String? forwarderId;
  final DateTime? createdAt;
  final DateTime? reviewedAt;

  bool get isPending => status == 'pending';

  factory FreightApplication.fromJson(Map<String, dynamic> j) => FreightApplication(
        id: _s(j['id']),
        companyName: _s(j['company_name']),
        countryCode: _s(j['country_code']),
        description: _sn(j['description']),
        lanes: [for (final l in _ml(j['lanes'])) Lane.fromJson(l)],
        modes: _sl(j['modes']),
        incoterms: _sl(j['incoterms']),
        certifications: _sl(j['certifications']),
        status: _s(j['status'], 'pending'),
        reviewNote: _sn(j['review_note']),
        forwarderId: _sn(j['forwarder_id']),
        createdAt: _dt(j['created_at']),
        reviewedAt: _dt(j['reviewed_at']),
      );
}

class ShipmentRequest {
  const ShipmentRequest({
    required this.id,
    required this.originCountry,
    required this.originPlace,
    required this.destinationCountry,
    required this.destinationPlace,
    required this.cargoDescription,
    this.hsCode,
    this.weightKg,
    this.volumeCbm,
    required this.mode,
    this.containerType,
    this.containerCount,
    required this.incoterm,
    required this.readyDate,
    required this.currency,
    this.landedCostRef,
    required this.status,
    this.outcome,
    this.quoteCount = 0,
    this.expiresAt,
    this.awardedAt,
    this.awardedQuoteId,
    this.buyerId,
    this.closedAt,
    this.createdAt,
    this.hasQuoted = false,
  });

  final String id;
  final String originCountry;
  final String originPlace;
  final String destinationCountry;
  final String destinationPlace;
  final String cargoDescription;
  final String? hsCode;

  /// Exact decimal strings (3 decimals).
  final String? weightKg;
  final String? volumeCbm;
  final String mode;
  final String? containerType;
  final int? containerCount;
  final String incoterm;

  /// yyyy-MM-dd
  final String readyDate;
  final String currency;
  final String? landedCostRef;

  /// open | awarded | closed | expired
  final String status;

  /// completed | cancelled (when closed)
  final String? outcome;
  final int quoteCount;
  final DateTime? expiresAt;
  final DateTime? awardedAt;
  final String? awardedQuoteId;
  final String? buyerId;
  final DateTime? closedAt;
  final DateTime? createdAt;

  /// Forwarder inbox only.
  final bool hasQuoted;

  bool get isOpen => status == 'open';
  bool get isAwarded => status == 'awarded';
  bool get isCompleted => status == 'closed' && outcome == 'completed';

  ShipmentRequest copyWith({
    String? status,
    String? outcome,
    int? quoteCount,
    DateTime? awardedAt,
    String? awardedQuoteId,
    DateTime? closedAt,
    bool? hasQuoted,
    bool hideBuyer = false,
  }) =>
      ShipmentRequest(
        id: id,
        originCountry: originCountry,
        originPlace: originPlace,
        destinationCountry: destinationCountry,
        destinationPlace: destinationPlace,
        cargoDescription: cargoDescription,
        hsCode: hsCode,
        weightKg: weightKg,
        volumeCbm: volumeCbm,
        mode: mode,
        containerType: containerType,
        containerCount: containerCount,
        incoterm: incoterm,
        readyDate: readyDate,
        currency: currency,
        landedCostRef: landedCostRef,
        status: status ?? this.status,
        outcome: outcome ?? this.outcome,
        quoteCount: quoteCount ?? this.quoteCount,
        expiresAt: expiresAt,
        awardedAt: awardedAt ?? this.awardedAt,
        awardedQuoteId: hideBuyer ? null : (awardedQuoteId ?? this.awardedQuoteId),
        buyerId: hideBuyer ? null : buyerId,
        closedAt: closedAt ?? this.closedAt,
        createdAt: createdAt,
        hasQuoted: hasQuoted ?? this.hasQuoted,
      );

  factory ShipmentRequest.fromJson(Map<String, dynamic> j) => ShipmentRequest(
        id: _s(j['id']),
        originCountry: _s(j['origin_country']),
        originPlace: _s(j['origin_place']),
        destinationCountry: _s(j['destination_country']),
        destinationPlace: _s(j['destination_place']),
        cargoDescription: _s(j['cargo_description']),
        hsCode: _sn(j['hs_code']),
        weightKg: FreightDecimal.wire(j['weight_kg']),
        volumeCbm: FreightDecimal.wire(j['volume_cbm']),
        mode: _s(j['mode'], 'sea'),
        containerType: _sn(j['container_type']),
        containerCount: j['container_count'] == null ? null : _i(j['container_count']),
        incoterm: _s(j['incoterm'], 'FOB'),
        readyDate: _s(j['ready_date']),
        currency: _s(j['currency'], 'USD'),
        landedCostRef: _sn(j['landed_cost_ref']),
        status: _s(j['status'], 'open'),
        outcome: _sn(j['outcome']),
        quoteCount: _i(j['quote_count']),
        expiresAt: _dt(j['expires_at']),
        awardedAt: _dt(j['awarded_at']),
        awardedQuoteId: _sn(j['awarded_quote_id']),
        buyerId: _sn(j['buyer_id']),
        closedAt: _dt(j['closed_at']),
        createdAt: _dt(j['created_at']),
        hasQuoted: j['has_quoted'] == true,
      );
}

class QuoteLine {
  const QuoteLine({required this.label, required this.amount});

  final String label;

  /// Exact decimal string, up to 2 decimals.
  final String amount;

  factory QuoteLine.fromJson(Map<String, dynamic> j) =>
      QuoteLine(label: _s(j['label']), amount: FreightDecimal.wire(j['amount']) ?? '0');

  Map<String, dynamic> toJson() => {'label': label, 'amount': amount};
}

class Quote {
  const Quote({
    required this.id,
    required this.requestId,
    required this.forwarderId,
    required this.amount,
    required this.currency,
    required this.transitDays,
    this.validUntil,
    this.valid = true,
    this.inclusions = const [],
    this.exclusions = const [],
    this.breakdown = const [],
    this.terms,
    required this.status,
    this.revision = 1,
    this.createdAt,
    this.updatedAt,
    this.forwarder,
  });

  final String id;
  final String requestId;
  final String forwarderId;
  final String amount;
  final String currency;
  final int transitDays;
  final DateTime? validUntil;
  final bool valid;
  final List<String> inclusions;
  final List<String> exclusions;
  final List<QuoteLine> breakdown;
  final String? terms;

  /// submitted | accepted | rejected | withdrawn
  final String status;
  final int revision;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final ForwarderSummary? forwarder;

  int? get amountMinor => FreightDecimal.parseScaled(amount, 2);
  bool get isSubmitted => status == 'submitted';
  bool get isWithdrawn => status == 'withdrawn';
  bool get isAccepted => status == 'accepted';

  Quote copyWith({
    String? amount,
    int? transitDays,
    DateTime? validUntil,
    bool? valid,
    List<String>? inclusions,
    List<String>? exclusions,
    List<QuoteLine>? breakdown,
    String? terms,
    String? status,
    int? revision,
    DateTime? updatedAt,
    ForwarderSummary? forwarder,
  }) =>
      Quote(
        id: id,
        requestId: requestId,
        forwarderId: forwarderId,
        amount: amount ?? this.amount,
        currency: currency,
        transitDays: transitDays ?? this.transitDays,
        validUntil: validUntil ?? this.validUntil,
        valid: valid ?? this.valid,
        inclusions: inclusions ?? this.inclusions,
        exclusions: exclusions ?? this.exclusions,
        breakdown: breakdown ?? this.breakdown,
        terms: terms ?? this.terms,
        status: status ?? this.status,
        revision: revision ?? this.revision,
        createdAt: createdAt,
        updatedAt: updatedAt ?? this.updatedAt,
        forwarder: forwarder ?? this.forwarder,
      );

  factory Quote.fromJson(Map<String, dynamic> j) => Quote(
        id: _s(j['id']),
        requestId: _s(j['request_id']),
        forwarderId: _s(j['forwarder_id']),
        amount: FreightDecimal.wire(j['amount']) ?? '0',
        currency: _s(j['currency'], 'USD'),
        transitDays: _i(j['transit_days']),
        validUntil: _dt(j['valid_until']),
        valid: j['valid'] != false,
        inclusions: _sl(j['inclusions']),
        exclusions: _sl(j['exclusions']),
        breakdown: [for (final l in _ml(j['breakdown'])) QuoteLine.fromJson(l)],
        terms: _sn(j['terms']),
        status: _s(j['status'], 'submitted'),
        revision: _i(j['revision'], 1),
        createdAt: _dt(j['created_at']),
        updatedAt: _dt(j['updated_at']),
        forwarder: j['forwarder'] is Map
            ? ForwarderSummary.fromJson(_m(j['forwarder']))
            : null,
      );
}

class AcceptResult {
  const AcceptResult({required this.request, required this.quote});

  final ShipmentRequest request;
  final Quote quote;

  factory AcceptResult.fromJson(Object? json) {
    final j = _m(json);
    return AcceptResult(
      request: ShipmentRequest.fromJson(_m(j['request'])),
      quote: Quote.fromJson(_m(j['quote'])),
    );
  }
}

class ScorePart {
  const ScorePart({required this.value, required this.weight});

  /// 0-1 component score.
  final double value;
  final double weight;

  factory ScorePart.fromJson(Object? json) {
    final j = _m(json);
    return ScorePart(value: _d(j['value']), weight: _d(j['weight']));
  }
}

class ComparisonItem {
  const ComparisonItem({
    required this.rank,
    required this.score,
    required this.price,
    required this.transit,
    required this.rating,
    required this.adjustedRating,
    this.badges = const [],
    this.explanation = const [],
    required this.quote,
  });

  final int rank;

  /// 0-100, one decimal.
  final double score;
  final ScorePart price;
  final ScorePart transit;
  final ScorePart rating;
  final double adjustedRating;

  /// cheapest | fastest | top_rated
  final List<String> badges;

  /// Server-side English text; the UI renders its own localized explanation
  /// from the numeric parts and only falls back to this.
  final List<String> explanation;
  final Quote quote;

  ComparisonItem withRank(int r) => ComparisonItem(
        rank: r,
        score: score,
        price: price,
        transit: transit,
        rating: rating,
        adjustedRating: adjustedRating,
        badges: badges,
        explanation: explanation,
        quote: quote,
      );

  factory ComparisonItem.fromJson(Map<String, dynamic> j) {
    final b = _m(j['breakdown']);
    return ComparisonItem(
      rank: _i(j['rank'], 1),
      score: _d(j['score']),
      price: ScorePart.fromJson(b['price']),
      transit: ScorePart.fromJson(b['transit']),
      rating: ScorePart.fromJson(b['rating']),
      adjustedRating: _d(j['adjusted_rating']),
      badges: _sl(j['badges']),
      explanation: _sl(j['explanation']),
      quote: Quote.fromJson(_m(j['quote'])),
    );
  }
}

class ExcludedQuote {
  const ExcludedQuote({required this.quoteId, required this.reason});

  final String quoteId;

  /// forwarder_suspended | currency_mismatch | quote_expired
  final String reason;

  factory ExcludedQuote.fromJson(Map<String, dynamic> j) =>
      ExcludedQuote(quoteId: _s(j['quote_id']), reason: _s(j['reason']));
}

class Comparison {
  const Comparison({
    required this.requestId,
    required this.requestStatus,
    required this.currency,
    this.sort = 'score',
    this.items = const [],
    this.excluded = const [],
  });

  final String requestId;
  final String requestStatus;
  final String currency;
  final String sort;
  final List<ComparisonItem> items;
  final List<ExcludedQuote> excluded;

  Comparison withItems(List<ComparisonItem> next, String nextSort) => Comparison(
        requestId: requestId,
        requestStatus: requestStatus,
        currency: currency,
        sort: nextSort,
        items: next,
        excluded: excluded,
      );

  factory Comparison.fromJson(Object? json) {
    final j = _m(json);
    return Comparison(
      requestId: _s(j['request_id']),
      requestStatus: _s(j['request_status'], 'open'),
      currency: _s(j['currency'], 'USD'),
      sort: _s(j['sort'], 'score'),
      items: [for (final e in _ml(j['items'])) ComparisonItem.fromJson(e)],
      excluded: [for (final e in _ml(j['excluded'])) ExcludedQuote.fromJson(e)],
    );
  }
}

class RatingItem {
  const RatingItem({
    required this.id,
    required this.requestId,
    required this.forwarderId,
    required this.stars,
    this.comment,
    this.createdAt,
  });

  final String id;
  final String requestId;
  final String forwarderId;
  final int stars;
  final String? comment;
  final DateTime? createdAt;

  factory RatingItem.fromJson(Map<String, dynamic> j) => RatingItem(
        id: _s(j['id']),
        requestId: _s(j['request_id']),
        forwarderId: _s(j['forwarder_id']),
        stars: _i(j['stars'], 1),
        comment: _sn(j['comment']),
        createdAt: _dt(j['created_at']),
      );
}

/// Sorts a comparison locally. `score` is descending; `price`, `transit`
/// ascending; `rating` descending by adjusted rating. Ties follow the
/// contract: lower price, shorter transit, earlier submission, then id.
/// Prices are compared as exact scaled integers.
List<ComparisonItem> sortComparisonItems(
  List<ComparisonItem> items,
  String sort,
) {
  int byPrice(ComparisonItem a, ComparisonItem b) {
    final pa = a.quote.amountMinor ?? 1 << 52;
    final pb = b.quote.amountMinor ?? 1 << 52;
    return pa.compareTo(pb);
  }

  int byTransit(ComparisonItem a, ComparisonItem b) =>
      a.quote.transitDays.compareTo(b.quote.transitDays);

  int bySubmitted(ComparisonItem a, ComparisonItem b) {
    final ca = a.quote.createdAt;
    final cb = b.quote.createdAt;
    if (ca != null && cb != null) return ca.compareTo(cb);
    return 0;
  }

  int tie(ComparisonItem a, ComparisonItem b) {
    var c = byPrice(a, b);
    if (c != 0) return c;
    c = byTransit(a, b);
    if (c != 0) return c;
    c = bySubmitted(a, b);
    if (c != 0) return c;
    return a.quote.id.compareTo(b.quote.id);
  }

  final out = List<ComparisonItem>.of(items);
  out.sort((a, b) {
    int c;
    switch (sort) {
      case 'price':
        c = byPrice(a, b);
        break;
      case 'transit':
        c = byTransit(a, b);
        break;
      case 'rating':
        c = b.adjustedRating.compareTo(a.adjustedRating);
        break;
      default:
        c = b.score.compareTo(a.score);
    }
    return c != 0 ? c : tie(a, b);
  });
  return out;
}
