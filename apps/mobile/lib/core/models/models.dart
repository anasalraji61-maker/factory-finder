import 'package:factory_finder/core/utils/number_format.dart';

// ---------------------------------------------------------------------------
// Enums (json values follow contracts/schemas/common.schema.json)
// ---------------------------------------------------------------------------

T _enumFrom<T extends Enum>(
  List<T> values,
  String Function(T) jsonOf,
  String? s,
  T fallback,
) {
  for (final v in values) {
    if (jsonOf(v) == s) return v;
  }
  return fallback;
}

enum ListingKind {
  product('product'),
  rawMaterial('raw_material'),
  productionLine('production_line');

  const ListingKind(this.json);
  final String json;
}

ListingKind listingKindFromJson(String s) =>
    _enumFrom(ListingKind.values, (v) => v.json, s, ListingKind.product);

enum ItemCondition {
  brandNew('new'),
  used('used'),
  refurbished('refurbished');

  const ItemCondition(this.json);
  final String json;
}

ItemCondition itemConditionFromJson(String s) =>
    _enumFrom(ItemCondition.values, (v) => v.json, s, ItemCondition.brandNew);

enum TransportMode {
  seaLcl('sea_lcl'),
  seaFcl20('sea_fcl_20'),
  seaFcl40('sea_fcl_40'),
  seaFcl40hc('sea_fcl_40hc'),
  air('air'),
  rail('rail'),
  road('road');

  const TransportMode(this.json);
  final String json;
}

TransportMode transportModeFromJson(String s) =>
    _enumFrom(TransportMode.values, (v) => v.json, s, TransportMode.seaLcl);

enum Incoterm {
  exw('EXW'),
  fca('FCA'),
  fob('FOB'),
  cfr('CFR'),
  cif('CIF'),
  dap('DAP'),
  ddp('DDP');

  const Incoterm(this.json);
  final String json;
}

Incoterm incotermFromJson(String s) =>
    _enumFrom(Incoterm.values, (v) => v.json, s, Incoterm.fob);

enum TrustBand {
  green('green'),
  yellow('yellow'),
  red('red'),
  unknown('unknown');

  const TrustBand(this.json);
  final String json;
}

TrustBand trustBandFromJson(String s) =>
    _enumFrom(TrustBand.values, (v) => v.json, s, TrustBand.unknown);

// ---------------------------------------------------------------------------
// JSON helpers
// ---------------------------------------------------------------------------

double? _dbl(Object? v) => (v as num?)?.toDouble();
int? _int(Object? v) => (v as num?)?.toInt();
Map<String, dynamic> _map(Object? v) => Map<String, dynamic>.from(v as Map);
Map<String, dynamic>? _mapOrNull(Object? v) => v == null ? null : _map(v);

// ---------------------------------------------------------------------------
// Value types
// ---------------------------------------------------------------------------

const Map<String, String> _currencySymbols = {
  'USD': r'$',
  'EUR': '€',
  'CNY': '¥',
  'GBP': '£',
};
const Set<String> _zeroDecimalCurrencies = {'IQD', 'JPY', 'KRW', 'VND'};

class Money {
  const Money({required this.amount, required this.currency});

  /// Decimal as string, e.g. "1234.50" (CLAUDE.md rule 8).
  final String amount;
  final String currency;

  double get value => double.tryParse(amount) ?? 0;

  String format() {
    final digits = _zeroDecimalCurrencies.contains(currency) ? 0 : 2;
    final n = formatDecimalString(amount, fractionDigits: digits);
    final sym = _currencySymbols[currency];
    return sym != null ? '$sym$n' : '$currency $n';
  }

  /// [format] wrapped in an LTR isolate, for embedding in translated (RTL)
  /// sentences so the currency never reorders around the number.
  String formatIsolated() => isolateLtr(format());

  factory Money.fromJson(Map<String, dynamic> j) => Money(
        amount: (j['amount'] ?? '0').toString(),
        currency: (j['currency'] as String?) ?? 'USD',
      );

  Map<String, dynamic> toJson() => {'amount': amount, 'currency': currency};
}

class MoneyRange {
  const MoneyRange({required this.min, required this.max});

  final Money min;
  final Money max;

  String format() {
    if (min.amount == max.amount && min.currency == max.currency) {
      return min.format();
    }
    return '${min.format()} – ${max.format()}';
  }

  String formatIsolated() => isolateLtr(format());

  factory MoneyRange.fromJson(Map<String, dynamic> j) => MoneyRange(
        min: Money.fromJson(_map(j['min'])),
        max: Money.fromJson(_map(j['max'])),
      );

  Map<String, dynamic> toJson() => {'min': min.toJson(), 'max': max.toJson()};
}

class DayRange {
  const DayRange({required this.min, required this.max});

  final int min;
  final int max;

  factory DayRange.fromJson(Map<String, dynamic> j) =>
      DayRange(min: _int(j['min']) ?? 0, max: _int(j['max']) ?? 0);

  Map<String, dynamic> toJson() => {'min': min, 'max': max};
}

class GeoPoint {
  const GeoPoint({required this.lat, required this.lon});

  final double lat;
  final double lon;

  factory GeoPoint.fromJson(Map<String, dynamic> j) =>
      GeoPoint(lat: _dbl(j['lat']) ?? 0, lon: _dbl(j['lon']) ?? 0);

  Map<String, dynamic> toJson() => {'lat': lat, 'lon': lon};
}

class Location {
  const Location({required this.countryCode, this.city, this.point});

  final String countryCode;
  final String? city;
  final GeoPoint? point;

  factory Location.fromJson(Map<String, dynamic> j) => Location(
        countryCode: j['country_code'] as String,
        city: j['city'] as String?,
        point: _mapOrNull(j['point']) == null
            ? null
            : GeoPoint.fromJson(_map(j['point'])),
      );

  Map<String, dynamic> toJson() => {
        'country_code': countryCode,
        if (city != null) 'city': city,
        if (point != null) 'point': point!.toJson(),
      };
}

class SupplierSummary {
  const SupplierSummary({
    required this.id,
    required this.name,
    required this.location,
    this.yearsInBusiness,
    this.verified = false,
    this.trustScore,
    this.trustBand = TrustBand.unknown,
  });

  final String id;
  final String name;
  final Location location;
  final int? yearsInBusiness;
  final bool verified;
  final int? trustScore;
  final TrustBand trustBand;

  factory SupplierSummary.fromJson(Map<String, dynamic> j) => SupplierSummary(
        id: j['id'].toString(),
        name: (j['name'] as String?) ?? '',
        location: _mapOrNull(j['location']) == null
            ? const Location(countryCode: 'XX')
            : Location.fromJson(_map(j['location'])),
        yearsInBusiness: _int(j['years_in_business']),
        verified: (j['verified'] as bool?) ?? false,
        trustScore: _int(j['trust_score']),
        trustBand: j['trust_band'] == null
            ? TrustBand.unknown
            : trustBandFromJson(j['trust_band'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'location': location.toJson(),
        if (yearsInBusiness != null) 'years_in_business': yearsInBusiness,
        'verified': verified,
        if (trustScore != null) 'trust_score': trustScore,
        'trust_band': trustBand.json,
      };
}

class Listing {
  const Listing({
    required this.id,
    required this.source,
    required this.kind,
    required this.title,
    required this.price,
    required this.supplier,
    this.sourceUrl,
    this.condition = ItemCondition.brandNew,
    this.titleAr,
    this.category,
    this.images = const [],
    this.unit = 'piece',
    this.moq,
    this.incoterm,
    this.unitWeightKg,
    this.unitVolumeM3,
    this.hsCode,
    this.leadTimeDays,
    this.origin,
  });

  final String id;
  final String source;
  final String? sourceUrl;
  final ListingKind kind;
  final ItemCondition condition;
  final String title;
  final String? titleAr;
  final String? category;
  final List<String> images;
  final MoneyRange price;
  final String unit;
  final int? moq;
  final Incoterm? incoterm;
  final double? unitWeightKg;
  final double? unitVolumeM3;
  final String? hsCode;
  final DayRange? leadTimeDays;
  final SupplierSummary supplier;
  final Location? origin;

  String displayTitle(String languageCode) {
    if (languageCode == 'ar' && titleAr != null && titleAr!.isNotEmpty) {
      return titleAr!;
    }
    return title;
  }

  factory Listing.fromJson(Map<String, dynamic> j) => Listing(
        id: j['id'].toString(),
        source: (j['source'] as String?) ?? 'unknown',
        sourceUrl: j['source_url'] as String?,
        kind: listingKindFromJson((j['kind'] as String?) ?? 'product'),
        condition: j['condition'] == null
            ? ItemCondition.brandNew
            : itemConditionFromJson(j['condition'] as String),
        title: (j['title'] as String?) ?? '',
        titleAr: j['title_ar'] as String?,
        category: j['category'] as String?,
        images: ((j['images'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        price: _mapOrNull(j['price']) == null
            ? const MoneyRange(
                min: Money(amount: '0', currency: 'USD'),
                max: Money(amount: '0', currency: 'USD'),
              )
            : MoneyRange.fromJson(_map(j['price'])),
        unit: (j['unit'] as String?) ?? 'piece',
        moq: _int(j['moq']),
        incoterm: j['incoterm'] == null
            ? null
            : incotermFromJson(j['incoterm'] as String),
        unitWeightKg: _dbl(j['unit_weight_kg']),
        unitVolumeM3: _dbl(j['unit_volume_m3']),
        hsCode: j['hs_code'] as String?,
        leadTimeDays: _mapOrNull(j['lead_time_days']) == null
            ? null
            : DayRange.fromJson(_map(j['lead_time_days'])),
        supplier: SupplierSummary.fromJson(_map(j['supplier'])),
        origin: _mapOrNull(j['origin']) == null
            ? null
            : Location.fromJson(_map(j['origin'])),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'source': source,
        if (sourceUrl != null) 'source_url': sourceUrl,
        'kind': kind.json,
        'condition': condition.json,
        'title': title,
        if (titleAr != null) 'title_ar': titleAr,
        if (category != null) 'category': category,
        'images': images,
        'price': price.toJson(),
        'unit': unit,
        if (moq != null) 'moq': moq,
        if (incoterm != null) 'incoterm': incoterm!.json,
        if (unitWeightKg != null) 'unit_weight_kg': unitWeightKg,
        if (unitVolumeM3 != null) 'unit_volume_m3': unitVolumeM3,
        if (hsCode != null) 'hs_code': hsCode,
        if (leadTimeDays != null) 'lead_time_days': leadTimeDays!.toJson(),
        'supplier': supplier.toJson(),
        if (origin != null) 'origin': origin!.toJson(),
      };
}

class CostLine {
  const CostLine({
    required this.stage,
    required this.description,
    required this.amount,
    required this.estimate,
    this.source,
    this.fxRate,
    this.quoted = false,
  });

  final String stage;
  final String description;
  final Money amount;
  final bool estimate;

  /// True when the amount is an exact forwarder quote (never a range).
  final bool quoted;
  final String? source;
  final String? fxRate;

  factory CostLine.fromJson(Map<String, dynamic> j) => CostLine(
        stage: (j['stage'] as String?) ?? 'other',
        description: (j['description'] as String?) ?? '',
        amount: Money.fromJson(_map(j['amount'])),
        estimate: (j['estimate'] as bool?) ?? true,
        source: j['source'] as String?,
        fxRate: j['fx_rate']?.toString(),
        quoted: (j['quoted'] as bool?) ?? false,
      );

  Map<String, dynamic> toJson() => {
        'stage': stage,
        'description': description,
        'amount': amount.toJson(),
        'estimate': estimate,
        if (quoted) 'quoted': true,
        if (source != null) 'source': source,
        if (fxRate != null) 'fx_rate': fxRate,
      };
}

/// Low/base/high of a landed-cost total under one stress scenario.
class MoneyBand {
  const MoneyBand({
    required this.low,
    required this.base,
    required this.high,
    this.shockPct,
    this.goodsCurrency,
  });

  final Money low;
  final Money base;
  final Money high;
  final String? shockPct;
  final String? goodsCurrency;

  factory MoneyBand.fromJson(Map<String, dynamic> j) => MoneyBand(
        low: Money.fromJson(_mapOrNull(j['low']) ?? const {}),
        base: Money.fromJson(_mapOrNull(j['base']) ?? const {}),
        high: Money.fromJson(_mapOrNull(j['high']) ?? const {}),
        shockPct: j['shock_pct']?.toString(),
        goodsCurrency: j['goods_currency']?.toString(),
      );

  Map<String, dynamic> toJson() => {
        'low': low.toJson(),
        'base': base.toJson(),
        'high': high.toJson(),
        if (shockPct != null) 'shock_pct': shockPct,
        if (goodsCurrency != null) 'goods_currency': goodsCurrency,
      };
}

/// Optional "what if" stress ranges of an option (not forecasts).
class CostSensitivity {
  const CostSensitivity({
    required this.currency,
    this.freight,
    this.fx,
    this.combined,
    this.estimate = true,
    this.note,
  });

  final String currency;
  final MoneyBand? freight;
  final MoneyBand? fx;
  final MoneyBand? combined;
  final bool estimate;
  final String? note;

  bool get isEmpty => freight == null && fx == null && combined == null;

  static MoneyBand? _band(Object? v) {
    if (v is! Map) return null;
    return MoneyBand.fromJson(Map<String, dynamic>.from(v));
  }

  /// Returns null when [v] is not an object (a malformed block never breaks the quote).
  static CostSensitivity? tryParse(Object? v) {
    if (v is! Map) return null;
    final j = Map<String, dynamic>.from(v);
    try {
      return CostSensitivity(
        currency: (j['currency'] as String?) ?? 'USD',
        freight: _band(j['freight']),
        fx: _band(j['fx']),
        combined: _band(j['combined']),
        estimate: (j['estimate'] as bool?) ?? true,
        note: j['note']?.toString(),
      );
    } catch (_) {
      return null;
    }
  }

  Map<String, dynamic> toJson() => {
        'currency': currency,
        if (freight != null) 'freight': freight!.toJson(),
        if (fx != null) 'fx': fx!.toJson(),
        if (combined != null) 'combined': combined!.toJson(),
        'estimate': estimate,
        if (note != null) 'note': note,
      };
}

class LandedCostOption {
  const LandedCostOption({
    required this.mode,
    required this.lines,
    required this.total,
    required this.transitDays,
    this.originHub,
    this.destinationHub,
    this.routeSummary,
    this.co2Kg,
    this.recommended = false,
    this.warnings = const [],
    this.sensitivity,
  });

  final TransportMode mode;
  final List<CostLine> lines;
  final MoneyRange total;
  final DayRange transitDays;
  final String? originHub;
  final String? destinationHub;
  final String? routeSummary;
  final double? co2Kg;
  final bool recommended;
  final List<String> warnings;

  /// Optional stress ranges ("what if"); null on older servers.
  final CostSensitivity? sensitivity;

  factory LandedCostOption.fromJson(Map<String, dynamic> j) => LandedCostOption(
        mode: transportModeFromJson((j['mode'] as String?) ?? ''),
        lines: ((j['lines'] as List?) ?? const [])
            .map((e) => CostLine.fromJson(_map(e)))
            .toList(),
        total: MoneyRange.fromJson(_map(j['total'])),
        transitDays: DayRange.fromJson(_map(j['transit_days'])),
        originHub: j['origin_hub'] as String?,
        destinationHub: j['destination_hub'] as String?,
        routeSummary: j['route_summary'] as String?,
        co2Kg: _dbl(j['co2_kg']),
        recommended: (j['recommended'] as bool?) ?? false,
        warnings: ((j['warnings'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        sensitivity: CostSensitivity.tryParse(j['sensitivity']),
      );

  Map<String, dynamic> toJson() => {
        'mode': mode.json,
        if (originHub != null) 'origin_hub': originHub,
        if (destinationHub != null) 'destination_hub': destinationHub,
        if (routeSummary != null) 'route_summary': routeSummary,
        'lines': lines.map((e) => e.toJson()).toList(),
        'total': total.toJson(),
        'transit_days': transitDays.toJson(),
        if (co2Kg != null) 'co2_kg': co2Kg,
        'recommended': recommended,
        'warnings': warnings,
        if (sensitivity != null) 'sensitivity': sensitivity!.toJson(),
      };
}

class LandedCostQuote {
  const LandedCostQuote({
    required this.id,
    required this.currency,
    required this.options,
    required this.createdAt,
    this.origin,
    this.destination,
    this.assumptions = const [],
    this.warnings = const [],
  });

  final String id;
  final String currency;
  final List<LandedCostOption> options;
  final DateTime createdAt;
  final Location? origin;
  final Location? destination;
  final List<String> assumptions;

  /// Quote-level warnings (e.g. de minimis hint); empty on older servers.
  final List<String> warnings;

  factory LandedCostQuote.fromJson(Map<String, dynamic> j) => LandedCostQuote(
        id: j['id'].toString(),
        currency: (j['currency'] as String?) ?? 'USD',
        options: ((j['options'] as List?) ?? const [])
            .map((e) => LandedCostOption.fromJson(_map(e)))
            .toList(),
        createdAt: DateTime.tryParse((j['created_at'] ?? '').toString()) ??
            DateTime.now().toUtc(),
        origin: _mapOrNull(j['origin']) == null
            ? null
            : Location.fromJson(_map(j['origin'])),
        destination: _mapOrNull(j['destination']) == null
            ? null
            : Location.fromJson(_map(j['destination'])),
        assumptions: ((j['assumptions'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        warnings: ((j['warnings'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'currency': currency,
        if (origin != null) 'origin': origin!.toJson(),
        if (destination != null) 'destination': destination!.toJson(),
        'options': options.map((e) => e.toJson()).toList(),
        'assumptions': assumptions,
        if (warnings.isNotEmpty) 'warnings': warnings,
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}

class TrustFactor {
  const TrustFactor({
    required this.key,
    required this.impact,
    required this.explanation,
    this.explanationAr,
  });

  final String key;
  final int impact;
  final String explanation;
  final String? explanationAr;

  factory TrustFactor.fromJson(Map<String, dynamic> j) => TrustFactor(
        key: (j['key'] as String?) ?? '',
        impact: _int(j['impact']) ?? 0,
        explanation: (j['explanation'] as String?) ?? '',
        explanationAr: j['explanation_ar'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'impact': impact,
        'explanation': explanation,
        if (explanationAr != null) 'explanation_ar': explanationAr,
      };
}

class TrustDataGap {
  const TrustDataGap({required this.key, required this.label, this.labelAr});

  final String key;
  final String label;
  final String? labelAr;

  String display(String lang) =>
      (lang == 'ar' && labelAr != null && labelAr!.isNotEmpty) ? labelAr! : label;
}

/// Tolerant: ints 0-100; a fractional double <= 1.0 (older servers) is scaled.
int? parseConfidence(Object? v) {
  if (v is! num) return null;
  var n = v.toDouble();
  if (v is double && n <= 1.0) n = n * 100;
  return n.round().clamp(0, 100).toInt();
}

List<TrustDataGap> parseDataGaps(Object? v) {
  if (v is! List) return const <TrustDataGap>[];
  final out = <TrustDataGap>[];
  for (final e in v) {
    if (e is! Map) continue;
    final key = e['key']?.toString() ?? '';
    final label = e['label']?.toString() ?? key;
    if (key.isEmpty && label.isEmpty) continue;
    out.add(TrustDataGap(
      key: key,
      label: label,
      labelAr: e['label_ar']?.toString(),
    ));
  }
  return out;
}

class TrustScore {
  const TrustScore({
    required this.supplierId,
    required this.score,
    required this.band,
    required this.factors,
    this.confidence,
    this.dataGaps = const <TrustDataGap>[],
    this.flags = const <String>[],
    this.modelVersion,
  });

  final String supplierId;
  final int score;
  final TrustBand band;
  final List<TrustFactor> factors;

  /// Trust v2 (additive): 0-100, how much evidence backs the score.
  final int? confidence;
  final List<TrustDataGap> dataGaps;
  final List<String> flags;
  final String? modelVersion;

  factory TrustScore.fromJson(Map<String, dynamic> j) => TrustScore(
        supplierId: j['supplier_id'] as String,
        score: _int(j['score']) ?? 0,
        band: trustBandFromJson((j['band'] as String?) ?? ''),
        factors: ((j['factors'] as List?) ?? const [])
            .map((e) => TrustFactor.fromJson(_map(e)))
            .toList(),
        confidence: parseConfidence(j['confidence']),
        dataGaps: parseDataGaps(j['data_gaps']),
        flags: ((j['flags'] is List) ? j['flags'] as List : const [])
            .whereType<String>()
            .toList(),
        modelVersion: j['model_version'] is String ? j['model_version'] as String : null,
      );

  Map<String, dynamic> toJson() => {
        'supplier_id': supplierId,
        'score': score,
        'band': band.json,
        'factors': factors.map((e) => e.toJson()).toList(),
      };
}

class PageResult<T> {
  const PageResult({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<T> items;
  final int total;
  final int page;
  final int pageSize;

  static PageResult<T> fromJson<T>(
    Map<String, dynamic> j,
    T Function(Map<String, dynamic>) item,
  ) {
    return PageResult<T>(
      items: ((j['items'] as List?) ?? const [])
          .map((e) => item(_map(e)))
          .toList(),
      total: _int(j['total']) ?? 0,
      page: _int(j['page']) ?? 1,
      pageSize: _int(j['page_size']) ?? 20,
    );
  }
}
