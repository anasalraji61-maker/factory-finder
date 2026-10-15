import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/mock_freight_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart' show FreightOverride;
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class FreightRepository {
  // Identity / forwarder side
  Future<Whoami> whoami();
  Future<FreightApplication> apply(ApplicationDraft draft);
  Future<FreightPage<FreightApplication>> myApplications();
  Future<FreightPage<ShipmentRequest>> inbox({String? cursor, int limit = 20});
  Future<FreightPage<Quote>> myQuotes({String? status, String? cursor, int limit = 20});

  // Buyer side
  Future<ShipmentRequest> createRequest(RequestDraft draft);
  Future<FreightPage<ShipmentRequest>> myRequests({String? status, String? cursor, int limit = 20});
  Future<ShipmentRequest> getRequest(String id);
  Future<ShipmentRequest> closeRequest(String id);
  Future<Comparison> compare(String requestId, {String sort = 'score'});
  Future<AcceptResult> acceptQuote(String quoteId);

  /// The awarded quote as a landed-cost `freight_override` (owner only;
  /// 409 `quote_not_awarded` otherwise).
  Future<FreightOverride> landedCostInput(String quoteId);
  Future<RatingItem> rateForwarder(String requestId, int stars, {String? comment});

  // Quotes (forwarder)
  Future<Quote> submitQuote(String requestId, QuoteDraft draft);
  Future<Quote> reviseQuote(String quoteId, QuoteDraft draft);
  Future<Quote> withdrawQuote(String quoteId);

  // Abuse reports. Always resolve to nothing on 202.
  Future<void> reportRequest(String requestId, String reason, {String? details});
  Future<void> reportQuote(String quoteId, String reason, {String? details});
  Future<void> reportForwarder(String forwarderId, String reason, {String? details});
}

/// Finds the caller's own quote on [requestId] (one quote per request) by
/// scanning its quotes newest first, at most [maxPages] pages.
Future<Quote?> findMyQuoteForRequest(
  FreightRepository repo,
  String requestId, {
  int maxPages = 5,
}) async {
  String? cursor;
  for (var i = 0; i < maxPages; i++) {
    final page = await repo.myQuotes(cursor: cursor, limit: 50);
    for (final q in page.items) {
      if (q.requestId == requestId) return q;
    }
    if (!page.hasMore) return null;
    cursor = page.nextCursor;
  }
  return null;
}

class LiveFreightRepository implements FreightRepository {
  LiveFreightRepository(this._api);

  final ApiClient _api;

  static String _enc(String s) => Uri.encodeComponent(s);

  static ApiException _bad() => ApiException(
        status: 502,
        code: 'bad_response',
        message: 'Unexpected response from freight service',
      );

  static Map<String, dynamic> _obj(dynamic json) {
    if (json is Map) return Map<String, dynamic>.from(json);
    throw _bad();
  }

  static Map<String, dynamic> _q({String? status, String? cursor, int? limit}) => {
        if (status != null && status.isNotEmpty) 'status': status,
        if (cursor != null && cursor.isNotEmpty) 'cursor': cursor,
        if (limit != null) 'limit': limit,
      };

  @override
  Future<Whoami> whoami() async =>
      Whoami.fromJson(_obj(await _api.get('/v1/freight/me')));

  @override
  Future<FreightApplication> apply(ApplicationDraft draft) async =>
      FreightApplication.fromJson(
        _obj(await _api.post('/v1/freight/applications', body: draft.toJson())),
      );

  @override
  Future<FreightPage<FreightApplication>> myApplications() async =>
      FreightPage.fromJson(
        _obj(await _api.get('/v1/freight/applications/mine')),
        FreightApplication.fromJson,
      );

  @override
  Future<FreightPage<ShipmentRequest>> inbox({String? cursor, int limit = 20}) async =>
      FreightPage.fromJson(
        _obj(await _api.get('/v1/freight/forwarders/me/inbox',
            query: _q(cursor: cursor, limit: limit))),
        ShipmentRequest.fromJson,
      );

  @override
  Future<FreightPage<Quote>> myQuotes({String? status, String? cursor, int limit = 20}) async =>
      FreightPage.fromJson(
        _obj(await _api.get('/v1/freight/forwarders/me/quotes',
            query: _q(status: status, cursor: cursor, limit: limit))),
        Quote.fromJson,
      );

  @override
  Future<ShipmentRequest> createRequest(RequestDraft draft) async =>
      ShipmentRequest.fromJson(
        _obj(await _api.post('/v1/freight/requests', body: draft.toJson())),
      );

  @override
  Future<FreightPage<ShipmentRequest>> myRequests({String? status, String? cursor, int limit = 20}) async =>
      FreightPage.fromJson(
        _obj(await _api.get('/v1/freight/requests',
            query: _q(status: status, cursor: cursor, limit: limit))),
        ShipmentRequest.fromJson,
      );

  @override
  Future<ShipmentRequest> getRequest(String id) async =>
      ShipmentRequest.fromJson(_obj(await _api.get('/v1/freight/requests/${_enc(id)}')));

  @override
  Future<ShipmentRequest> closeRequest(String id) async => ShipmentRequest.fromJson(
        _obj(await _api.post('/v1/freight/requests/${_enc(id)}/close')),
      );

  @override
  Future<Comparison> compare(String requestId, {String sort = 'score'}) async =>
      Comparison.fromJson(_obj(await _api.get(
        '/v1/freight/requests/${_enc(requestId)}/comparison',
        query: {'sort': sort},
      )));

  @override
  Future<AcceptResult> acceptQuote(String quoteId) async => AcceptResult.fromJson(
        _obj(await _api.post('/v1/freight/quotes/${_enc(quoteId)}/accept')),
      );

  @override
  Future<FreightOverride> landedCostInput(String quoteId) async => FreightOverride.fromJson(
        _obj(await _api.get('/v1/freight/quotes/${_enc(quoteId)}/landed-cost-input')),
      );

  @override
  Future<RatingItem> rateForwarder(String requestId, int stars, {String? comment}) async {
    final c = comment?.trim();
    return RatingItem.fromJson(_obj(await _api.post(
      '/v1/freight/requests/${_enc(requestId)}/rating',
      body: {'stars': stars, if (c != null && c.isNotEmpty) 'comment': c},
    )));
  }

  @override
  Future<Quote> submitQuote(String requestId, QuoteDraft draft) async => Quote.fromJson(
        _obj(await _api.post('/v1/freight/requests/${_enc(requestId)}/quotes',
            body: draft.toJson())),
      );

  @override
  Future<Quote> reviseQuote(String quoteId, QuoteDraft draft) async => Quote.fromJson(
        _obj(await _api.put('/v1/freight/quotes/${_enc(quoteId)}', body: draft.toJson())),
      );

  @override
  Future<Quote> withdrawQuote(String quoteId) async => Quote.fromJson(
        _obj(await _api.post('/v1/freight/quotes/${_enc(quoteId)}/withdraw')),
      );

  Map<String, dynamic> _report(String reason, String? details) {
    final d = details?.trim();
    return {'reason': reason, if (d != null && d.isNotEmpty) 'details': d};
  }

  @override
  Future<void> reportRequest(String requestId, String reason, {String? details}) async {
    await _api.post('/v1/freight/requests/${_enc(requestId)}/report',
        body: _report(reason, details));
  }

  @override
  Future<void> reportQuote(String quoteId, String reason, {String? details}) async {
    await _api.post('/v1/freight/quotes/${_enc(quoteId)}/report',
        body: _report(reason, details));
  }

  @override
  Future<void> reportForwarder(String forwarderId, String reason, {String? details}) async {
    await _api.post('/v1/freight/forwarders/${_enc(forwarderId)}/report',
        body: _report(reason, details));
  }
}

/// Mock mode keeps one in-memory marketplace for the whole app session.
final freightRepositoryProvider = Provider<FreightRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockFreightRepository() : LiveFreightRepository(api);
});

/// Bumped after every mutation so open lists reload.
final freightRefreshProvider = StateProvider<int>((ref) => 0);
