import 'package:factory_finder/core/models/models.dart';

enum SortOption {
  relevance('relevance'),
  priceLow('price_asc'),
  priceHigh('price_desc'),
  trust('trust'),
  moq('moq');

  const SortOption(this.api);

  /// Value of the `sort` query parameter of GET /v1/search.
  final String api;
}

/// Immutable search query + filters; usable as a Riverpod family key.
class ListingQuery {
  const ListingQuery({
    this.query = '',
    this.kind,
    this.condition,
    this.originCountry,
    this.maxMoq,
    this.verifiedOnly = false,
    this.category,
    this.supplierId,
    this.sort = SortOption.relevance,
    this.minPrice,
    this.maxPrice,
  });

  final String query;
  final ListingKind? kind;
  final ItemCondition? condition;
  final String? originCountry;
  final int? maxMoq;
  final bool verifiedOnly;
  final String? category;
  final String? supplierId;
  final SortOption sort;

  /// Unit price bounds in USD (`min_price` / `max_price` of GET /v1/search).
  final double? minPrice;
  final double? maxPrice;

  int get activeFilterCount =>
      (kind != null ? 1 : 0) +
      (condition != null ? 1 : 0) +
      (originCountry != null ? 1 : 0) +
      (maxMoq != null ? 1 : 0) +
      (minPrice != null ? 1 : 0) +
      (maxPrice != null ? 1 : 0) +
      (verifiedOnly ? 1 : 0);

  ListingQuery copyWith({
    String? query,
    SortOption? sort,
    ListingKind? kind,
    bool clearKind = false,
    String? category,
    bool clearCategory = false,
  }) {
    return ListingQuery(
      query: query ?? this.query,
      kind: clearKind ? null : (kind ?? this.kind),
      condition: condition,
      originCountry: originCountry,
      maxMoq: maxMoq,
      verifiedOnly: verifiedOnly,
      category: clearCategory ? null : (category ?? this.category),
      supplierId: supplierId,
      sort: sort ?? this.sort,
      minPrice: minPrice,
      maxPrice: maxPrice,
    );
  }

  @override
  bool operator ==(Object other) =>
      other is ListingQuery &&
      other.query == query &&
      other.kind == kind &&
      other.condition == condition &&
      other.originCountry == originCountry &&
      other.maxMoq == maxMoq &&
      other.verifiedOnly == verifiedOnly &&
      other.category == category &&
      other.supplierId == supplierId &&
      other.sort == sort &&
      other.minPrice == minPrice &&
      other.maxPrice == maxPrice;

  @override
  int get hashCode => Object.hash(
        query,
        kind,
        condition,
        originCountry,
        maxMoq,
        verifiedOnly,
        category,
        supplierId,
        sort,
        minPrice,
        maxPrice,
      );
}

/// Query-string form of a price bound: "10" for whole numbers, else "10.5".
String priceParam(double v) =>
    v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toString();

/// Parses a price text field: null when blank, malformed or negative.
double? parsePriceInput(String text) {
  final v = double.tryParse(text.trim().replaceAll(',', '.'));
  if (v == null || v.isNaN || v.isInfinite || v < 0) return null;
  return v;
}

/// Category keys per listing kind (labels: `cat.<key>`).
const Map<ListingKind, List<String>> kCategoriesByKind = {
  ListingKind.product: ['electronics', 'textiles', 'furniture', 'packaging'],
  ListingKind.rawMaterial: ['steel', 'plastic_resin', 'aluminum', 'cotton', 'chemicals'],
  ListingKind.productionLine: [
    'food_processing',
    'plastics_machinery',
    'packaging_machinery',
    'metalworking',
  ],
};

/// Node of GET /v1/categories (bilingual tree; top level = listing kinds).
class CategoryNode {
  const CategoryNode({
    required this.slug,
    required this.name,
    required this.nameAr,
    this.children = const [],
  });

  final String slug;
  final String name;
  final String nameAr;
  final List<CategoryNode> children;

  String label(String languageCode) =>
      languageCode == 'ar' && nameAr.isNotEmpty ? nameAr : name;

  factory CategoryNode.fromJson(Map<String, dynamic> j) => CategoryNode(
        slug: (j['slug'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        nameAr: (j['name_ar'] ?? '').toString(),
        children: ((j['children'] as List?) ?? const [])
            .map((e) => CategoryNode.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList(),
      );
}
