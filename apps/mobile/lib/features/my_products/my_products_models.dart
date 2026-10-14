import 'package:factory_finder/core/models/models.dart';

/// Lifecycle of a supplier-owned listing (`status` of OwnedListing).
enum ListingStatus {
  draft('draft'),
  published('published'),
  archived('archived'),

  /// Moderated: not searchable, visible to the owner only.
  pendingReview('pending_review'),
  hidden('hidden');

  const ListingStatus(this.json);
  final String json;

  /// True for the two moderation states (owner can edit/delete, not publish).
  bool get isModerated => this == pendingReview || this == hidden;
}

ListingStatus listingStatusFromJson(Object? s) {
  for (final v in ListingStatus.values) {
    if (v.json == s) return v;
  }
  return ListingStatus.draft;
}

/// Units offered in the editor (the server accepts any non-empty unit).
const List<String> kProductUnits = ['piece', 'kg', 'ton', 'set', 'm', 'line'];

/// Currencies offered for the price range.
const List<String> kProductCurrencies = ['USD', 'EUR', 'CNY', 'IQD', 'TRY', 'AED'];

const int kMaxProductImages = 8;

double? _num(Object? v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v);
  return null;
}

int? _intOrNull(Object? v) {
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v);
  return null;
}

String? _nonEmpty(Object? v) {
  if (v is! String) return null;
  final t = v.trim();
  return t.isEmpty ? null : t;
}

Map<String, dynamic>? _asMap(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : null;

Money _money(Object? v) {
  final m = _asMap(v);
  if (m == null) return const Money(amount: '0', currency: 'USD');
  return Money(
    amount: (m['amount'] ?? '0').toString(),
    currency: (m['currency'] ?? 'USD').toString(),
  );
}

/// A listing owned by the signed-in supplier (`OwnedListing`): the public
/// listing fields plus status and timestamps. Parsing never throws on a
/// missing optional field.
class OwnedListing {
  const OwnedListing({
    required this.id,
    required this.status,
    required this.kind,
    required this.condition,
    required this.title,
    required this.price,
    this.titleAr,
    this.description,
    this.descriptionAr,
    this.category,
    this.images = const <String>[],
    this.unit = 'piece',
    this.moq,
    this.incoterm,
    this.unitWeightKg,
    this.unitVolumeM3,
    this.hsCode,
    this.leadTimeDays,
    this.origin,
    this.createdAt,
    this.updatedAt,
    this.publishedAt,
    this.moderationSource,
    this.moderationReason,
    this.moderatedAt,
  });

  final String id;
  final ListingStatus status;
  final ListingKind kind;
  final ItemCondition condition;
  final String title;
  final String? titleAr;
  final String? description;
  final String? descriptionAr;
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
  final Location? origin;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final DateTime? publishedAt;

  /// `auto` | `report` | `admin` (only while moderated).
  final String? moderationSource;

  /// Why the listing is pending_review/hidden. Never holds reporter data.
  final String? moderationReason;
  final DateTime? moderatedAt;

  bool get isModerated => status.isModerated;

  String displayTitle(String languageCode) {
    final ar = titleAr;
    if (languageCode == 'ar' && ar != null && ar.isNotEmpty) return ar;
    return title;
  }

  OwnedListing copyWith({
    ListingStatus? status,
    DateTime? updatedAt,
    DateTime? publishedAt,
    String? moderationSource,
    String? moderationReason,
    DateTime? moderatedAt,
    bool clearModeration = false,
  }) =>
      OwnedListing(
        id: id,
        status: status ?? this.status,
        kind: kind,
        condition: condition,
        title: title,
        titleAr: titleAr,
        description: description,
        descriptionAr: descriptionAr,
        category: category,
        images: images,
        price: price,
        unit: unit,
        moq: moq,
        incoterm: incoterm,
        unitWeightKg: unitWeightKg,
        unitVolumeM3: unitVolumeM3,
        hsCode: hsCode,
        leadTimeDays: leadTimeDays,
        origin: origin,
        createdAt: createdAt,
        updatedAt: updatedAt ?? this.updatedAt,
        publishedAt: publishedAt ?? this.publishedAt,
        moderationSource: clearModeration ? null : (moderationSource ?? this.moderationSource),
        moderationReason: clearModeration ? null : (moderationReason ?? this.moderationReason),
        moderatedAt: clearModeration ? null : (moderatedAt ?? this.moderatedAt),
      );

  factory OwnedListing.fromJson(Map<String, dynamic> j) {
    final price = _asMap(j['price']);
    final lead = _asMap(j['lead_time_days']);
    final origin = _asMap(j['origin']);
    final cc = origin?['country_code'];
    return OwnedListing(
      id: (j['id'] ?? '').toString(),
      status: listingStatusFromJson(j['status']),
      kind: listingKindFromJson((j['kind'] ?? 'product').toString()),
      condition: itemConditionFromJson((j['condition'] ?? 'new').toString()),
      title: (j['title'] ?? '').toString(),
      titleAr: j['title_ar'] as String?,
      description: j['description'] as String?,
      descriptionAr: j['description_ar'] as String?,
      category: j['category'] as String?,
      images: ((j['images'] is List) ? j['images'] as List : const <Object?>[])
          .map((e) => e.toString())
          .toList(),
      price: MoneyRange(
        min: _money(price?['min']),
        max: _money(price?['max']),
      ),
      unit: (j['unit'] ?? 'piece').toString(),
      moq: _intOrNull(j['moq']),
      incoterm: j['incoterm'] is String && (j['incoterm'] as String).isNotEmpty
          ? incotermFromJson(j['incoterm'] as String)
          : null,
      unitWeightKg: _num(j['unit_weight_kg']),
      unitVolumeM3: _num(j['unit_volume_m3']),
      hsCode: j['hs_code'] as String?,
      leadTimeDays: lead == null
          ? null
          : DayRange(min: _intOrNull(lead['min']) ?? 0, max: _intOrNull(lead['max']) ?? 0),
      origin: (origin == null || cc is! String)
          ? null
          : Location(countryCode: cc, city: origin['city'] as String?),
      createdAt: DateTime.tryParse((j['created_at'] ?? '').toString()),
      updatedAt: DateTime.tryParse((j['updated_at'] ?? '').toString()),
      publishedAt: DateTime.tryParse((j['published_at'] ?? '').toString()),
      moderationSource: _nonEmpty(j['moderation_source']),
      moderationReason: _nonEmpty(j['moderation_reason']),
      moderatedAt: DateTime.tryParse((j['moderated_at'] ?? '').toString()),
    );
  }

  /// Form state for editing this listing.
  ProductDraft toDraft() => ProductDraft(
        kind: kind,
        condition: condition,
        title: title,
        titleAr: titleAr ?? '',
        description: description ?? '',
        descriptionAr: descriptionAr ?? '',
        category: category ?? '',
        priceMin: price.min.amount,
        priceMax: price.max.amount,
        currency: price.min.currency,
        unit: unit,
        moq: moq == null ? '1' : '$moq',
        incoterm: incoterm,
        unitWeightKg: unitWeightKg == null ? '' : '$unitWeightKg',
        unitVolumeM3: unitVolumeM3 == null ? '' : '$unitVolumeM3',
        hsCode: hsCode ?? '',
        leadMin: leadTimeDays == null ? '' : '${leadTimeDays!.min}',
        leadMax: leadTimeDays == null ? '' : '${leadTimeDays!.max}',
        images: List<String>.of(images),
        origin: origin ?? const Location(countryCode: 'IQ'),
      );
}

/// Editor form values, all as the user typed them (strings). Money stays a
/// string end to end (CLAUDE.md rule 8); [toBody] never touches doubles for
/// prices.
class ProductDraft {
  const ProductDraft({
    this.kind = ListingKind.product,
    this.condition = ItemCondition.brandNew,
    this.title = '',
    this.titleAr = '',
    this.description = '',
    this.descriptionAr = '',
    this.category = '',
    this.priceMin = '',
    this.priceMax = '',
    this.currency = 'USD',
    this.unit = 'piece',
    this.moq = '1',
    this.incoterm,
    this.unitWeightKg = '',
    this.unitVolumeM3 = '',
    this.hsCode = '',
    this.leadMin = '',
    this.leadMax = '',
    this.images = const <String>[],
    this.origin = const Location(countryCode: 'IQ'),
  });

  final ListingKind kind;
  final ItemCondition condition;
  final String title;
  final String titleAr;
  final String description;
  final String descriptionAr;
  final String category;
  final String priceMin;
  final String priceMax;
  final String currency;
  final String unit;
  final String moq;
  final Incoterm? incoterm;
  final String unitWeightKg;
  final String unitVolumeM3;
  final String hsCode;
  final String leadMin;
  final String leadMax;
  final List<String> images;
  final Location origin;
}
