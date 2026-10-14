import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class RfqRepository {
  RfqRepository(this._api, [MockRfqBackend? backend])
      : _mock = backend ?? MockRfqBackend();

  final ApiClient _api;
  final MockRfqBackend _mock;

  Future<PageResult<RfqRequest>> list(RfqFilter f) async {
    if (_api.isMock) {
      await mockDelay(300);
      final items = filterRequests(_mock.requests, f);
      return PageResult<RfqRequest>(
        items: items,
        total: items.length,
        page: 1,
        pageSize: 50,
      );
    }
    final json = await _api.get('/v1/requests', query: {
      'scope': f.mine ? 'mine' : 'public',
      if (f.mine && f.status != null) 'status': f.status!.json,
      if (f.kind != null) 'kind': f.kind!.json,
      'page': 1,
      'page_size': 50,
    });
    return _page(json, RfqRequest.fromJson);
  }

  Future<RfqRequest> get(String id) async {
    if (_api.isMock) {
      await mockDelay(200);
      for (final r in _mock.requests) {
        if (r.id == id) return r;
      }
      throw ApiException(status: 404, code: 'not_found', message: 'Request $id not found');
    }
    final json = await _api.get('/v1/requests/$id');
    return RfqRequest.fromJson(Map<String, dynamic>.from(json as Map));
  }

  Future<List<Offer>> offers(String requestId) async {
    if (_api.isMock) {
      await mockDelay(250);
      return List<Offer>.of(_mock.offers[requestId] ?? const <Offer>[]);
    }
    final json = await _api.get('/v1/requests/$requestId/offers');
    return _page(json, Offer.fromJson).items;
  }

  Future<RfqRequest> create(RfqDraft draft) async {
    if (_api.isMock) {
      await mockDelay(400);
      return _mock.create(draft);
    }
    final json = await _api.post('/v1/requests', body: draft.toJson());
    return RfqRequest.fromJson(Map<String, dynamic>.from(json as Map));
  }

  Future<Deal> accept(Offer offer) async {
    if (_api.isMock) {
      await mockDelay(400);
      return _mock.accept(offer.id);
    }
    final json = await _api.post('/v1/offers/${offer.id}/accept');
    return Deal.fromJson(Map<String, dynamic>.from(json as Map));
  }
}

/// Accepts either a bare JSON list or a `{items: [...]}` page.
PageResult<T> _page<T>(dynamic json, T Function(Map<String, dynamic>) item) {
  if (json is List) {
    final items =
        json.map((e) => item(Map<String, dynamic>.from(e as Map))).toList();
    return PageResult<T>(items: items, total: items.length, page: 1, pageSize: items.length);
  }
  return PageResult.fromJson<T>(Map<String, dynamic>.from(json as Map), item);
}

/// Kept alive for the whole session so mock state (created requests,
/// accepted offers) survives navigation. Do NOT `watch` apiClientProvider
/// here with autoDispose.
final rfqRepositoryProvider = Provider<RfqRepository>(
  (ref) => RfqRepository(ref.watch(apiClientProvider)),
);

final rfqListProvider =
    FutureProvider.autoDispose.family<PageResult<RfqRequest>, RfqFilter>(
  (ref, f) => ref.watch(rfqRepositoryProvider).list(f),
);

final rfqDetailProvider = FutureProvider.autoDispose.family<RfqRequest, String>(
  (ref, id) => ref.watch(rfqRepositoryProvider).get(id),
);

final rfqOffersProvider = FutureProvider.autoDispose.family<List<Offer>, String>(
  (ref, id) => ref.watch(rfqRepositoryProvider).offers(id),
);

/// Deals accepted in this session, by request id (the buyer's "Commission &
/// payment" section hangs off these). Memory only.
final acceptedDealsProvider = StateProvider<Map<String, Deal>>(
  (ref) => const <String, Deal>{},
);
