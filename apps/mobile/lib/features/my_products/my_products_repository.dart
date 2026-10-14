import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// In-memory stand-in for `/v1/my/listings` (mock mode and tests).
class MockMyListingsBackend {
  MockMyListingsBackend({List<OwnedListing> seed = const <OwnedListing>[]})
      : items = List<OwnedListing>.of(seed);

  final List<OwnedListing> items;
  int _seq = 0;

  OwnedListing find(String id) {
    for (final l in items) {
      if (l.id == id) return l;
    }
    throw ApiException(status: 404, code: 'not_found', message: 'Listing $id not found');
  }

  int _indexOf(String id) {
    find(id);
    return items.indexWhere((l) => l.id == id);
  }

  OwnedListing _fromDraft(String id, ProductDraft d, ListingStatus status,
      {DateTime? createdAt, DateTime? publishedAt}) {
    final j = buildListingBody(d);
    final now = DateTime.now().toUtc();
    return OwnedListing.fromJson(<String, dynamic>{
      ...j,
      'id': id,
      'status': status.json,
      'created_at': (createdAt ?? now).toIso8601String(),
      'updated_at': now.toIso8601String(),
      if (publishedAt != null) 'published_at': publishedAt.toIso8601String(),
    });
  }

  OwnedListing create(ProductDraft d) {
    _seq++;
    final l = _fromDraft('lst_mock_my_${_seq.toString().padLeft(3, '0')}', d, ListingStatus.draft);
    items.insert(0, l);
    return l;
  }

  OwnedListing update(String id, ProductDraft d) {
    final i = _indexOf(id);
    final old = items[i];
    final l = _fromDraft(id, d, old.status,
            createdAt: old.createdAt, publishedAt: old.publishedAt)
        .copyWith(
      moderationSource: old.moderationSource,
      moderationReason: old.moderationReason,
      moderatedAt: old.moderatedAt,
    );
    items[i] = l;
    return l;
  }

  OwnedListing setStatus(String id, ListingStatus status) {
    final i = _indexOf(id);
    final old = items[i];
    if (old.isModerated && status == ListingStatus.published) {
      throw ApiException(
        status: 409,
        code: 'listing_moderated',
        message: 'Listing is under moderation',
      );
    }
    if (status == ListingStatus.draft && old.status != ListingStatus.published) {
      throw ApiException(
        status: 409,
        code: 'not_published',
        message: 'Listing is not published',
      );
    }
    final now = DateTime.now().toUtc();
    final l = old.copyWith(
      status: status,
      updatedAt: now,
      publishedAt: status == ListingStatus.published ? now : null,
    );
    items[i] = l;
    return l;
  }

  void delete(String id) {
    items.removeAt(_indexOf(id));
  }

  /// Test/mock helper: puts a listing into a moderation state.
  OwnedListing moderate(
    String id,
    ListingStatus status, {
    String source = 'report',
    String? reason,
  }) {
    final i = _indexOf(id);
    final l = items[i].copyWith(
      status: status,
      moderationSource: source,
      moderationReason: reason,
      moderatedAt: DateTime.now().toUtc(),
    );
    items[i] = l;
    return l;
  }
}

class MyListingsRepository {
  MyListingsRepository(this._api, [MockMyListingsBackend? backend])
      : _mock = backend ?? MockMyListingsBackend();

  final ApiClient _api;
  final MockMyListingsBackend _mock;

  Future<PageResult<OwnedListing>> list({
    ListingStatus? status,
    int page = 1,
    int pageSize = 50,
  }) async {
    if (_api.isMock) {
      await mockDelay(200);
      final all = _mock.items
          .where((l) => status == null || l.status == status)
          .toList();
      final start = (page - 1) * pageSize;
      final slice = start >= all.length
          ? <OwnedListing>[]
          : all.sublist(start, (start + pageSize).clamp(0, all.length).toInt());
      return PageResult<OwnedListing>(
        items: slice,
        total: all.length,
        page: page,
        pageSize: pageSize,
      );
    }
    final json = await _api.get('/v1/my/listings', query: <String, dynamic>{
      if (status != null) 'status': status.json,
      'page': page,
      'page_size': pageSize,
    });
    return parseOwnedPage(json);
  }

  Future<OwnedListing> get(String id) async {
    if (_api.isMock) {
      await mockDelay(150);
      return _mock.find(id);
    }
    final json = await _api.get('/v1/my/listings/$id');
    return _one(json);
  }

  Future<OwnedListing> create(ProductDraft draft) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mock.create(draft);
    }
    final json = await _api.post('/v1/my/listings', body: buildListingBody(draft));
    return _one(json);
  }

  Future<OwnedListing> update(String id, ProductDraft draft) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mock.update(id, draft);
    }
    final json = await _api.put('/v1/my/listings/$id', body: buildListingBody(draft));
    return _one(json);
  }

  Future<void> delete(String id) async {
    if (_api.isMock) {
      await mockDelay(200);
      _mock.delete(id);
      return;
    }
    await _api.delete('/v1/my/listings/$id');
  }

  Future<OwnedListing> publish(String id) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mock.setStatus(id, ListingStatus.published);
    }
    final json = await _api.post('/v1/my/listings/$id/publish');
    return _tolerantOne(json, id);
  }

  Future<OwnedListing> unpublish(String id) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mock.setStatus(id, ListingStatus.draft);
    }
    final json = await _api.post('/v1/my/listings/$id/unpublish');
    return _tolerantOne(json, id);
  }

  OwnedListing _one(dynamic json) {
    if (json is Map) return OwnedListing.fromJson(Map<String, dynamic>.from(json));
    throw ApiException(status: null, code: 'bad_response', message: 'Unexpected response');
  }

  /// publish/unpublish may answer with an empty body: re-read the listing.
  Future<OwnedListing> _tolerantOne(dynamic json, String id) async {
    if (json is Map && json['id'] != null) {
      return OwnedListing.fromJson(Map<String, dynamic>.from(json));
    }
    return get(id);
  }
}

/// Parses `{items,total,page,page_size}` tolerantly (skips malformed rows).
PageResult<OwnedListing> parseOwnedPage(dynamic json) {
  final m = json is Map ? Map<String, dynamic>.from(json) : <String, dynamic>{};
  final raw = m['items'] is List ? m['items'] as List : const <Object?>[];
  final items = <OwnedListing>[
    for (final e in raw)
      if (e is Map) OwnedListing.fromJson(Map<String, dynamic>.from(e)),
  ];
  int asInt(Object? v, int fallback) => v is num ? v.toInt() : fallback;
  return PageResult<OwnedListing>(
    items: items,
    total: asInt(m['total'], items.length),
    page: asInt(m['page'], 1),
    pageSize: asInt(m['page_size'], 50),
  );
}

final myListingsRepositoryProvider = Provider<MyListingsRepository>(
  (ref) => MyListingsRepository(ref.watch(apiClientProvider)),
);

/// Leaf category tree used when /v1/categories is empty (mock) or fails.
/// Mirrors the gateway's category slugs.
const List<CategoryNode> kFallbackCategories = <CategoryNode>[
  CategoryNode(slug: 'product', name: 'Products', nameAr: 'منتجات', children: <CategoryNode>[
    CategoryNode(slug: 'furniture', name: 'Furniture', nameAr: 'أثاث'),
    CategoryNode(slug: 'lighting', name: 'Lighting', nameAr: 'إضاءة'),
    CategoryNode(slug: 'solar_energy', name: 'Solar energy', nameAr: 'طاقة شمسية'),
    CategoryNode(slug: 'kitchenware', name: 'Kitchenware', nameAr: 'أدوات مطبخ'),
    CategoryNode(slug: 'tires_auto', name: 'Tires & auto parts', nameAr: 'إطارات وقطع غيار السيارات'),
    CategoryNode(slug: 'apparel', name: 'Apparel & modest wear', nameAr: 'ملابس وأزياء محتشمة'),
    CategoryNode(slug: 'tools', name: 'Tools', nameAr: 'عدد وأدوات'),
    CategoryNode(slug: 'pumps_hvac', name: 'Pumps & air conditioning', nameAr: 'مضخات وتكييف'),
  ]),
  CategoryNode(slug: 'raw_material', name: 'Raw materials', nameAr: 'مواد أولية', children: <CategoryNode>[
    CategoryNode(slug: 'plastics', name: 'Plastics & granules', nameAr: 'بلاستيك وحبيبات'),
    CategoryNode(slug: 'metals', name: 'Metals', nameAr: 'معادن'),
    CategoryNode(slug: 'textiles', name: 'Textiles & yarn', nameAr: 'منسوجات وخيوط'),
    CategoryNode(slug: 'paper_wood', name: 'Paper & wood', nameAr: 'ورق وخشب'),
  ]),
  CategoryNode(slug: 'production_line', name: 'Production lines', nameAr: 'خطوط إنتاج', children: <CategoryNode>[
    CategoryNode(slug: 'food_beverage', name: 'Food & beverage lines', nameAr: 'خطوط الأغذية والمشروبات'),
    CategoryNode(slug: 'plastics_machinery', name: 'Plastics machinery', nameAr: 'ماكينات البلاستيك'),
    CategoryNode(slug: 'metalworking', name: 'Metalworking & CNC', nameAr: 'تشغيل المعادن وCNC'),
    CategoryNode(slug: 'construction_machinery', name: 'Construction materials machinery', nameAr: 'ماكينات مواد البناء'),
    CategoryNode(slug: 'paper_packaging', name: 'Paper & packaging lines', nameAr: 'خطوط الورق والتغليف'),
  ]),
];

/// Leaf categories allowed for [kind] in [tree] (top level = kinds). Falls
/// back to [kFallbackCategories] when the tree has no node for the kind.
List<CategoryNode> leafCategoriesFor(List<CategoryNode> tree, ListingKind kind) {
  List<CategoryNode> from(List<CategoryNode> nodes) {
    for (final n in nodes) {
      if (n.slug == kind.json) return n.children;
    }
    return const <CategoryNode>[];
  }

  final live = from(tree);
  return live.isNotEmpty ? live : from(kFallbackCategories);
}

/// Category tree for the editor; never throws (falls back to the built-in tree).
final productCategoriesProvider = FutureProvider.autoDispose<List<CategoryNode>>((ref) async {
  try {
    final tree = await ref.watch(discoverRepositoryProvider).categories();
    return tree.isEmpty ? kFallbackCategories : tree;
  } catch (_) {
    return kFallbackCategories;
  }
});
