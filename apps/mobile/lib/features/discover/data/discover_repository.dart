import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// UI category chip keys -> real sourcing category slugs (GET /v1/categories).
/// A null slug means the backend has no equivalent: the key is sent as a
/// keyword instead of a category filter.
const Map<String, String?> kLiveCategorySlugs = {
  'electronics': null,
  'textiles': 'apparel',
  'furniture': 'furniture',
  'packaging': null,
  'steel': 'metals',
  'plastic_resin': 'plastics',
  'aluminum': 'metals',
  'cotton': 'textiles',
  'chemicals': null,
  'food_processing': 'food_beverage',
  'plastics_machinery': 'plastics_machinery',
  'packaging_machinery': 'paper_packaging',
  'metalworking': 'metalworking',
};

class DiscoverRepository {
  DiscoverRepository(this._api);

  final ApiClient _api;

  Future<PageResult<Listing>> search(ListingQuery q) async {
    if (_api.isMock) {
      await mockDelay();
      return filterMockListings(q);
    }
    final cat = q.category;
    final hasSlugMap = cat != null && kLiveCategorySlugs.containsKey(cat);
    final categorySlug = cat == null
        ? null
        : (hasSlugMap ? kLiveCategorySlugs[cat] : cat);
    final keyword = (hasSlugMap && categorySlug == null && q.query.isEmpty)
        ? cat!.replaceAll('_', ' ')
        : q.query;
    final json = await _api.get('/v1/search', query: {
      if (keyword.isNotEmpty) 'q': keyword,
      if (q.kind != null) 'kind': q.kind!.json,
      if (q.condition != null) 'condition': q.condition!.json,
      if (q.originCountry != null) 'origin_country': q.originCountry,
      if (q.maxMoq != null) 'moq_max': q.maxMoq,
      if (q.verifiedOnly) 'verified_only': true,
      if (categorySlug != null) 'category': categorySlug,
      'page': 1,
      'page_size': 50,
    });
    final page = PageResult.fromJson<Listing>(
      Map<String, dynamic>.from(json as Map),
      Listing.fromJson,
    );
    return applyClientSort(page, q);
  }

  /// The search contract has no sort/supplier params: handled client-side.
  static PageResult<Listing> applyClientSort(PageResult<Listing> page, ListingQuery q) {
    final items = page.items
        .where((l) => q.supplierId == null || l.supplier.id == q.supplierId)
        .toList();
    switch (q.sort) {
      case SortOption.relevance:
        break;
      case SortOption.priceLow:
        items.sort((a, b) => a.price.min.value.compareTo(b.price.min.value));
      case SortOption.priceHigh:
        items.sort((a, b) => b.price.max.value.compareTo(a.price.max.value));
      case SortOption.trust:
        items.sort((a, b) =>
            (b.supplier.trustScore ?? 0).compareTo(a.supplier.trustScore ?? 0));
    }
    return PageResult<Listing>(
      items: items,
      total: q.supplierId == null ? page.total : items.length,
      page: page.page,
      pageSize: page.pageSize,
    );
  }

  Future<List<CategoryNode>> categories() async {
    if (_api.isMock) {
      await mockDelay(150);
      return const <CategoryNode>[];
    }
    final json = await _api.get('/v1/categories');
    return ((json as List?) ?? const [])
        .map((e) => CategoryNode.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<List<Listing>> trending() async {
    if (_api.isMock) {
      await mockDelay(250);
      final sorted = [...mockListings]..sort((a, b) =>
          (b.supplier.trustScore ?? 0).compareTo(a.supplier.trustScore ?? 0));
      return sorted.take(8).toList();
    }
    final page = await search(const ListingQuery(sort: SortOption.trust));
    return page.items.take(8).toList();
  }

  Future<Listing> getListing(String id) async {
    if (_api.isMock) {
      await mockDelay(250);
      return mockListings.firstWhere(
        (l) => l.id == id,
        orElse: () => throw ApiException(
          status: 404,
          code: 'not_found',
          message: 'Listing $id not found',
        ),
      );
    }
    final json = await _api.get('/v1/listings/$id');
    return Listing.fromJson(Map<String, dynamic>.from(json as Map));
  }

  Future<SupplierSummary> getSupplier(String id) async {
    if (_api.isMock) {
      await mockDelay(200);
      final s = mockSuppliers[id];
      if (s == null) {
        throw ApiException(
          status: 404,
          code: 'not_found',
          message: 'Supplier $id not found',
        );
      }
      return s;
    }
    final json = await _api.get('/v1/suppliers/$id');
    return SupplierSummary.fromJson(Map<String, dynamic>.from(json as Map));
  }

  Future<TrustScore> getTrust(String supplierId) async {
    if (_api.isMock) {
      await mockDelay(200);
      final s = mockSuppliers[supplierId];
      if (s == null) {
        throw ApiException(
          status: 404,
          code: 'not_found',
          message: 'Supplier $supplierId not found',
        );
      }
      return mockTrustFor(s);
    }
    final json = await _api.get('/v1/trust/suppliers/$supplierId');
    return TrustScore.fromJson(Map<String, dynamic>.from(json as Map));
  }
}

final discoverRepositoryProvider = Provider<DiscoverRepository>(
  (ref) => DiscoverRepository(ref.watch(apiClientProvider)),
);

final listingsProvider =
    FutureProvider.autoDispose.family<PageResult<Listing>, ListingQuery>(
  (ref, q) => ref.watch(discoverRepositoryProvider).search(q),
);

final trendingProvider = FutureProvider.autoDispose<List<Listing>>(
  (ref) => ref.watch(discoverRepositoryProvider).trending(),
);

final listingProvider = FutureProvider.autoDispose.family<Listing, String>(
  (ref, id) => ref.watch(discoverRepositoryProvider).getListing(id),
);

final supplierProvider =
    FutureProvider.autoDispose.family<SupplierSummary, String>(
  (ref, id) => ref.watch(discoverRepositoryProvider).getSupplier(id),
);

final trustProvider = FutureProvider.autoDispose.family<TrustScore, String>(
  (ref, id) => ref.watch(discoverRepositoryProvider).getTrust(id),
);
