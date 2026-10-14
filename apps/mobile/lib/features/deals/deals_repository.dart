import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class DealsRepository {
  /// Mock only: remembers a deal created elsewhere. No-op for the live client.
  void track(Deal deal);

  Future<Deal> get(String dealId);

  /// Supplier: paid -> in_fulfilment (idempotent).
  Future<Deal> startFulfilment(String dealId);

  /// Supplier: sets delivered_at while in_fulfilment (idempotent).
  Future<Deal> markDelivered(String dealId);

  /// Buyer: in_fulfilment -> completed (idempotent).
  Future<Deal> confirmReceipt(String dealId);

  Future<DealEventList> events(String dealId);
}

class LiveDealsRepository implements DealsRepository {
  LiveDealsRepository(this._api);

  final ApiClient _api;

  static String _enc(String s) => Uri.encodeComponent(s);

  Deal _deal(dynamic json) {
    if (json is Map) return Deal.fromJson(Map<String, dynamic>.from(json));
    throw ApiException(
      status: 502,
      code: 'bad_response',
      message: 'Unexpected response from deals service',
    );
  }

  @override
  void track(Deal deal) {}

  @override
  Future<Deal> get(String dealId) async =>
      _deal(await _api.get('/v1/deals/${_enc(dealId)}'));

  @override
  Future<Deal> startFulfilment(String dealId) async =>
      _deal(await _api.post('/v1/deals/${_enc(dealId)}/fulfilment/start'));

  @override
  Future<Deal> markDelivered(String dealId) async =>
      _deal(await _api.post('/v1/deals/${_enc(dealId)}/delivered'));

  @override
  Future<Deal> confirmReceipt(String dealId) async =>
      _deal(await _api.post('/v1/deals/${_enc(dealId)}/confirm-receipt'));

  @override
  Future<DealEventList> events(String dealId) async =>
      DealEventList.fromJson(await _api.get('/v1/deals/${_enc(dealId)}/events'));
}

/// In-memory state machine mirroring rfq:
/// pending_payment -> paid -> in_fulfilment -> completed, with an immutable
/// event log. Wrong-state calls throw 409 `invalid_deal_transition`.
class MockDealsRepository implements DealsRepository {
  MockDealsRepository({this.delayMs = 0, DateTime Function()? clock})
      : _clock = clock ?? DateTime.now;

  /// Simulated latency; 0 (default) skips timers entirely.
  final int delayMs;
  final DateTime Function() _clock;

  final Map<String, Deal> _deals = <String, Deal>{};
  final Map<String, List<DealEvent>> _events = <String, List<DealEvent>>{};

  Future<void> _wait() async {
    if (delayMs > 0) await mockDelay(delayMs);
  }

  ApiException _err(int status, String code) =>
      ApiException(status: status, code: code, message: code);

  @override
  void track(Deal deal) {
    _deals.putIfAbsent(deal.id, () => deal);
    _events.putIfAbsent(deal.id, () => <DealEvent>[]);
  }

  Deal _find(String id) {
    final d = _deals[id];
    if (d == null) throw _err(404, 'not_found');
    return d;
  }

  Deal _apply(
    Deal deal,
    String action,
    String actor,
    String to, {
    DateTime? deliveredAt,
    DateTime? completedAt,
    DealPayment? payment,
  }) {
    final now = _clock().toUtc();
    final log = _events.putIfAbsent(deal.id, () => <DealEvent>[]);
    log.add(DealEvent(
      seq: log.length + 1,
      action: action,
      actorRole: actor,
      fromStatus: deal.status,
      toStatus: to,
      createdAt: now,
    ));
    final out = deal.copyWith(
      status: to,
      deliveredAt: deliveredAt,
      completedAt: completedAt,
      payment: payment,
    );
    _deals[deal.id] = out;
    return out;
  }

  /// Mock only: simulates the payments service reporting both invoices paid
  /// (pending_payment -> paid).
  Future<Deal> simulatePayment(String dealId) async {
    await _wait();
    final d = _find(dealId);
    if (d.status == kDealPaid) return d;
    if (d.status != kDealPendingPayment) throw _err(409, 'invalid_deal_transition');
    return _apply(
      d,
      'payment_paid',
      'system',
      kDealPaid,
      payment: const DealPayment(commission: 'paid', dealPayment: 'paid'),
    );
  }

  @override
  Future<Deal> get(String dealId) async {
    await _wait();
    return _find(dealId);
  }

  @override
  Future<Deal> startFulfilment(String dealId) async {
    await _wait();
    final d = _find(dealId);
    if (d.status == kDealInFulfilment) return d;
    if (d.status != kDealPaid) throw _err(409, 'invalid_deal_transition');
    return _apply(d, 'fulfilment_started', 'supplier', kDealInFulfilment);
  }

  @override
  Future<Deal> markDelivered(String dealId) async {
    await _wait();
    final d = _find(dealId);
    if (d.deliveredAt != null &&
        (d.status == kDealInFulfilment || d.status == kDealCompleted)) {
      return d;
    }
    if (d.status != kDealInFulfilment) throw _err(409, 'invalid_deal_transition');
    return _apply(
      d,
      'delivered',
      'supplier',
      kDealInFulfilment,
      deliveredAt: _clock().toUtc(),
    );
  }

  @override
  Future<Deal> confirmReceipt(String dealId) async {
    await _wait();
    final d = _find(dealId);
    if (d.status == kDealCompleted) return d;
    if (d.status != kDealInFulfilment) throw _err(409, 'invalid_deal_transition');
    return _apply(
      d,
      'receipt_confirmed',
      'buyer',
      kDealCompleted,
      completedAt: _clock().toUtc(),
    );
  }

  @override
  Future<DealEventList> events(String dealId) async {
    await _wait();
    _find(dealId);
    final items = List<DealEvent>.of(_events[dealId] ?? const <DealEvent>[]);
    return DealEventList(items: items, total: items.length);
  }
}

/// Kept alive for the session so mock deal state survives navigation.
final dealsRepositoryProvider = Provider<DealsRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockDealsRepository(delayMs: 250) : LiveDealsRepository(api);
});

final dealEventsProvider =
    FutureProvider.autoDispose.family<DealEventList, String>(
  (ref, dealId) => ref.watch(dealsRepositoryProvider).events(dealId),
);
