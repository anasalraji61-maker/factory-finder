import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/discover/data/search_facets.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('SearchFacets.tryParse', () {
    test('parses map-shaped counts', () {
      final f = SearchFacets.tryParse({
        'kind': {'product': 12, 'raw_material': 3},
        'condition': {'new': 10, 'used': 5},
        'origin_country': {'CN': 9},
        'category': {'metals': 2},
      })!;
      expect(f.kind['product'], 12);
      expect(f.condition['used'], 5);
      expect(f.originCountry['CN'], 9);
      expect(f.category['metals'], 2);
    });

    test('parses list-shaped counts and ignores junk', () {
      final f = SearchFacets.tryParse({
        'kind': [
          {'value': 'product', 'count': 4},
          {'key': 'raw_material', 'count': 1.0},
          {'value': 'x'},
          'junk',
        ],
        'condition': 'nope',
        'origin_country': {'CN': 'many', 'DE': 2},
      })!;
      expect(f.kind, {'product': 4, 'raw_material': 1});
      expect(f.condition, isEmpty);
      expect(f.originCountry, {'DE': 2});
    });

    test('returns null when absent or unusable', () {
      expect(SearchFacets.tryParse(null), isNull);
      expect(SearchFacets.tryParse('x'), isNull);
      expect(SearchFacets.tryParse(<String, dynamic>{}), isNull);
    });

    test('facetSuffix', () {
      expect(facetSuffix({'a': 3}, 'a'), ' (3)');
      expect(facetSuffix({'a': 3}, 'b'), '');
      expect(facetSuffix(null, 'a'), '');
    });
  });

  group('sort + mock facets', () {
    test('sort api values match the contract', () {
      expect(SortOption.values.map((o) => o.api).toList(),
          ['relevance', 'price_asc', 'price_desc', 'trust', 'moq']);
    });

    test('mock moq sort is ascending', () {
      final items = filterMockListings(const ListingQuery(sort: SortOption.moq)).items;
      for (var i = 1; i < items.length; i++) {
        expect((items[i - 1].moq ?? 1 << 30) <= (items[i].moq ?? 1 << 30), isTrue);
      }
    });

    test('mock page carries facets summing to the catalogue size', () {
      final page = filterMockListings(const ListingQuery());
      expect(page, isA<ListingPage>());
      final facets = (page as ListingPage).facets!;
      expect(facets.kind.values.fold<int>(0, (a, b) => a + b), mockListings.length);
    });
  });
}
