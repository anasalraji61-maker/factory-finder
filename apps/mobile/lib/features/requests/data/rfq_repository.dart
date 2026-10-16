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

  /// One page of requests. Pass the previous page's [RfqPage.nextCursor] as
  /// [cursor] to continue (keyset); without it the first page is returned.
  Future<RfqPage> list(RfqFilter f, {String? cursor, int pageSize = 50}) async {
    final hasCursor = cursor != null && cursor.isNotEmpty;
    if (_api.isMock) {
      await mockDelay(300);
      return _mock.listPage(f, cursor: hasCursor ? cursor : null, pageSize: pageSize);
    }
    final json = await _api.get('/v1/requests', query: {
      'scope': f.mine ? 'mine' : 'public',
      if (f.mine && f.status != null) 'status': f.status!.json,
      if (f.kind != null) 'kind': f.kind!.json,
      'page': 1,
      'page_size': pageSize,
      if (hasCursor) 'cursor': cursor,
    });
    if (json is List) {
      final items = json
          .map((e) => RfqRequest.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
      return RfqPage(items: items, total: items.length, page: 1, pageSize: items.length);
    }
    return RfqPage.fromJson(Map<String, dynamic>.from(json as Map));
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

  /// The signed-in supplier's own offers on [requestId]. Live: the server
  /// already limits `GET /v1/requests/{id}/offers` to the caller's offers
  /// for a supplier; mock: filtered by the mock user.
  Future<List<Offer>> myOffers(String requestId) async {
    if (_api.isMock) {
      await mockDelay(250);
      return _mock.myOffers(requestId);
    }
    final json = await _api.get('/v1/requests/$requestId/offers');
    return _page(json, Offer.fromJson).items;
  }

  /// Supplier submits an offer (POST /v1/requests/{id}/offers).
  Future<Offer> submitOffer(String requestId, OfferDraft draft) async {
    if (_api.isMock) {
      await mockDelay(400);
      return _mock.submitOffer(requestId, draft);
    }
    final json = await _api.post('/v1/requests/$requestId/offers', body: draft.toJson());
    return Offer.fromJson(Map<String, dynamic>.from(json as Map));
  }

  /// Supplier withdraws their offer (POST /v1/offers/{id}/withdraw).
  Future<Offer> withdrawOffer(Offer offer) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mock.withdrawOffer(offer.id);
    }
    final json = await _api.post('/v1/offers/${offer.id}/withdraw');
    return Offer.fromJson(Map<String, dynamic>.from(json as Map));
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
    FutureProvider.autoDispose.family<RfqPage, RfqFilter>(
  (ref, f) => ref.watch(rfqRepositoryProvider).list(f),
);

final rfqDetailProvider = FutureProvider.autoDispose.family<RfqRequest, String>(
  (ref, id) => ref.watch(rfqRepositoryProvider).get(id),
);

final rfqOffersProvider = FutureProvider.autoDispose.family<List<Offer>, String>(
  (ref, id) => ref.watch(rfqRepositoryProvider).offers(id),
);

/// The signed-in supplier's own offers on a request.
final myOffersProvider = FutureProvider.autoDispose.family<List<Offer>, String>(
  (ref, id) => ref.watch(rfqRepositoryProvider).myOffers(id),
);

/// Deals accepted in this session, by request id (the buyer's "Commission &
/// payment" section hangs off these). Memory only.
final acceptedDealsProvider = StateProvider<Map<String, Deal>>(
  (ref) => const <String, Deal>{},
);
