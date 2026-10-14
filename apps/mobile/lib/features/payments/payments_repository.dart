import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart' show kMockUserId;
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/payments/payments_models.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class PaymentsRepository {
  /// Invoices of one deal (gateway: GET /v1/invoices?deal_id=).
  Future<List<Invoice>> listForDeal(String dealId);

  Future<Invoice> get(String id);

  /// Idempotent: an open or paid invoice of the same deal and kind is returned.
  Future<Invoice> create(Deal deal, InvoiceKind kind);

  Future<Invoice> cancel(String id);
}

class LivePaymentsRepository implements PaymentsRepository {
  LivePaymentsRepository(this._api);

  final ApiClient _api;

  Invoice _one(dynamic json) {
    if (json is Map) return Invoice.fromJson(Map<String, dynamic>.from(json));
    throw ApiException(
      status: 502,
      code: 'bad_response',
      message: 'Unexpected response from payments service',
    );
  }

  @override
  Future<List<Invoice>> listForDeal(String dealId) async {
    final json = await _api.get('/v1/invoices', query: {
      'deal_id': dealId,
      'page': 1,
      'page_size': 50,
    });
    return parseInvoiceList(json);
  }

  @override
  Future<Invoice> get(String id) async =>
      _one(await _api.get('/v1/invoices/${Uri.encodeComponent(id)}'));

  @override
  Future<Invoice> create(Deal deal, InvoiceKind kind) async => _one(
        await _api.post('/v1/invoices', body: {
          'deal_id': deal.id,
          'kind': kind.json,
        }),
      );

  @override
  Future<Invoice> cancel(String id) async =>
      _one(await _api.post('/v1/invoices/${Uri.encodeComponent(id)}/cancel'));
}

/// In-memory simulation. Each [get] of an active invoice advances it:
/// awaiting_payment -> confirming (1, 2 confirmations) -> paid.
class MockPaymentsRepository implements PaymentsRepository {
  MockPaymentsRepository({this.delayMs = 250});

  /// Simulated latency; 0 skips timers entirely (used by widget tests).
  final int delayMs;

  final Map<String, Invoice> _items = <String, Invoice>{};
  final Map<String, int> _polls = <String, int>{};
  int _seq = 0;

  Future<void> _wait() async {
    if (delayMs > 0) await mockDelay(delayMs);
  }

  /// Synchronous create (idempotent per deal + kind while open or paid).
  Invoice createSync(Deal deal, InvoiceKind kind) {
    for (final i in _items.values) {
      if (i.dealId == deal.id &&
          i.kind == kind &&
          (i.status.isPollable ||
              i.status == InvoiceStatus.pending ||
              i.status == InvoiceStatus.paid)) {
        return i;
      }
    }
    _seq++;
    final amount =
        kind == InvoiceKind.commission ? deal.commission : deal.subtotal;
    final fixed = amount.value.toStringAsFixed(2);
    final now = DateTime.now().toUtc();
    final inv = Invoice(
      id: 'inv_mock_$_seq',
      dealId: deal.id,
      payerUserId: kMockUserId,
      payee: kind == InvoiceKind.commission ? 'platform' : 'supplier',
      kind: kind,
      amount: amount,
      status: InvoiceStatus.awaitingPayment,
      expiresAt: now.add(const Duration(minutes: 60)),
      provider: 'mock',
      payAddress: 'TMockAddressForFactoryFinder000$_seq',
      payUrl: null,
      payAmount: Money(amount: '${fixed}0$_seq', currency: 'USDT'),
      memo: 'FF-MOCK-${1000 + _seq}',
      createdAt: now,
    );
    _items[inv.id] = inv;
    _polls[inv.id] = 0;
    return inv;
  }

  @override
  Future<Invoice> create(Deal deal, InvoiceKind kind) async {
    await _wait();
    return createSync(deal, kind);
  }

  @override
  Future<List<Invoice>> listForDeal(String dealId) async {
    await _wait();
    return _items.values.where((i) => i.dealId == dealId).toList();
  }

  @override
  Future<Invoice> get(String id) async {
    await _wait();
    var inv = _items[id];
    if (inv == null) {
      throw ApiException(status: 404, code: 'not_found', message: 'Invoice not found');
    }
    if (inv.status.isPollable) {
      final n = (_polls[id] ?? 0) + 1;
      _polls[id] = n;
      if (n >= 4) {
        inv = inv.copyWith(
          status: InvoiceStatus.paid,
          confirmations: 3,
          paidAt: DateTime.now().toUtc(),
          txRef: 'mocktx$id',
        );
      } else if (n >= 2) {
        inv = inv.copyWith(
          status: InvoiceStatus.confirming,
          confirmations: n - 1,
        );
      }
      _items[id] = inv;
    }
    return inv;
  }

  @override
  Future<Invoice> cancel(String id) async {
    await _wait();
    final inv = _items[id];
    if (inv == null) {
      throw ApiException(status: 404, code: 'not_found', message: 'Invoice not found');
    }
    if (!inv.status.isCancellable) {
      throw ApiException(status: 409, code: 'conflict', message: 'Invoice cannot be cancelled');
    }
    final out = inv.copyWith(status: InvoiceStatus.failed, statusReason: 'cancelled');
    _items[id] = out;
    return out;
  }
}

/// Kept alive for the whole session so mock invoices survive navigation.
final paymentsRepositoryProvider = Provider<PaymentsRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockPaymentsRepository() : LivePaymentsRepository(api);
});

final dealInvoicesProvider =
    FutureProvider.autoDispose.family<List<Invoice>, String>(
  (ref, dealId) => ref.watch(paymentsRepositoryProvider).listForDeal(dealId),
);
