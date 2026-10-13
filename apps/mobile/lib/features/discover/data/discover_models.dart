import 'package:factory_finder/core/models/models.dart';

enum SortOption { relevance, priceLow, priceHigh, trust }

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

  int get activeFilterCount =>
      (kind != null ? 1 : 0) +
      (condition != null ? 1 : 0) +
      (originCountry != null ? 1 : 0) +
      (maxMoq != null ? 1 : 0) +
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
      other.sort == sort;

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
      );
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
