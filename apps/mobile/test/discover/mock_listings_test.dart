import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('catalogue has 24 listings across the three kinds', () {
    expect(mockListings.length, 24);
    for (final k in ListingKind.values) {
      expect(mockListings.any((l) => l.kind == k), isTrue);
    }
    final origins = mockListings.map((l) => l.origin!.countryCode).toSet();
    expect(origins, containsAll(['CN', 'DE', 'IT', 'TR', 'US']));
    expect(mockListings.map((l) => l.id).toSet().length, 24);
  });

  test('filters', () {
    expect(
      filterMockListings(const ListingQuery(kind: ListingKind.productionLine))
          .items
          .every((l) => l.kind == ListingKind.productionLine),
      isTrue,
    );
    final used = filterMockListings(const ListingQuery(condition: ItemCondition.used));
    expect(used.items, isNotEmpty);
    expect(used.items.every((l) => l.condition == ItemCondition.used), isTrue);

    final de = filterMockListings(const ListingQuery(originCountry: 'DE'));
    expect(de.items.every((l) => l.origin!.countryCode == 'DE'), isTrue);

    final moq = filterMockListings(const ListingQuery(maxMoq: 100));
    expect(moq.items.every((l) => (l.moq ?? 0) <= 100), isTrue);

    final verified = filterMockListings(const ListingQuery(verifiedOnly: true));
    expect(verified.items.every((l) => l.supplier.verified), isTrue);
    expect(verified.total < mockListings.length, isTrue);

    final bySupplier = filterMockListings(const ListingQuery(supplierId: 'sup_cn_006'));
    expect(bySupplier.items.length, 3);
  });

  test('text search works in English and Arabic', () {
    expect(filterMockListings(const ListingQuery(query: 'steel')).items, isNotEmpty);
    expect(filterMockListings(const ListingQuery(query: 'حديد')).items, isNotEmpty);
    expect(filterMockListings(const ListingQuery(query: 'zzzzzz')).items, isEmpty);
  });

  test('sorting', () {
    final low = filterMockListings(const ListingQuery(sort: SortOption.priceLow)).items;
    for (var i = 1; i < low.length; i++) {
      expect(low[i].price.min.value >= low[i - 1].price.min.value, isTrue);
    }
    final trust = filterMockListings(const ListingQuery(sort: SortOption.trust)).items;
    expect(trust.first.supplier.trustScore! >= trust.last.supplier.trustScore!, isTrue);
  });

  test('ListingQuery has value equality', () {
    expect(const ListingQuery(query: 'a'), const ListingQuery(query: 'a'));
    expect(const ListingQuery(query: 'a').hashCode, const ListingQuery(query: 'a').hashCode);
    expect(const ListingQuery(query: 'a') == const ListingQuery(query: 'b'), isFalse);
  });
}
