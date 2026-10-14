import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';

/// Invoice lifecycle states (contracts/openapi/payments.yaml InvoiceStatus).
/// [unknown] keeps parsing tolerant of states added by newer servers.
enum InvoiceStatus {
  pending('pending'),
  awaitingPayment('awaiting_payment'),
  confirming('confirming'),
  paid('paid'),
  expired('expired'),
  failed('failed'),
  refunded('refunded'),
  unknown('unknown');

  const InvoiceStatus(this.json);

  final String json;

  static InvoiceStatus parse(Object? raw) {
    final s = raw?.toString().trim().toLowerCase();
    for (final v in InvoiceStatus.values) {
      if (v.json == s) return v;
    }
    return InvoiceStatus.unknown;
  }

  /// Still moving: the screen keeps polling these.
  bool get isPollable =>
      this == InvoiceStatus.awaitingPayment || this == InvoiceStatus.confirming;

  /// The payer can still cancel (contract: pending / awaiting_payment only).
  bool get isCancellable =>
      this == InvoiceStatus.pending || this == InvoiceStatus.awaitingPayment;

  /// Payment details are shown while the invoice can still receive funds.
  bool get showsPayDetails =>
      this == InvoiceStatus.pending ||
      this == InvoiceStatus.awaitingPayment ||
      this == InvoiceStatus.confirming;

  bool get isFinal =>
      this == InvoiceStatus.paid ||
      this == InvoiceStatus.expired ||
      this == InvoiceStatus.failed ||
      this == InvoiceStatus.refunded;
}

enum InvoiceKind {
  commission('commission'),
  dealPayment('deal_payment'),
  unknown('unknown');

  const InvoiceKind(this.json);

  final String json;

  static InvoiceKind parse(Object? raw) {
    final s = raw?.toString().trim().toLowerCase();
    for (final v in InvoiceKind.values) {
      if (v.json == s) return v;
    }
    return InvoiceKind.unknown;
  }
}

class Invoice {
  const Invoice({
    required this.id,
    required this.dealId,
    required this.kind,
    required this.amount,
    required this.status,
    required this.expiresAt,
    required this.createdAt,
    this.payerUserId = '',
    this.payee = '',
    this.statusReason,
    this.provider = '',
    this.payAddress,
    this.payUrl,
    this.payAmount,
    this.memo = '',
    this.txRef,
    this.confirmations = 0,
    this.paidAt,
  });

  final String id;
  final String dealId;
  final String payerUserId;
  final String payee;
  final InvoiceKind kind;
  final Money amount;
  final InvoiceStatus status;
  final String? statusReason;
  final DateTime expiresAt;
  final String provider;
  final String? payAddress;
  final String? payUrl;

  /// Exact amount to send (USDT adds a unique sub-cent suffix). Never rounded.
  final Money? payAmount;
  final String memo;
  final String? txRef;
  final int confirmations;
  final DateTime? paidAt;
  final DateTime createdAt;

  Invoice copyWith({
    InvoiceStatus? status,
    String? statusReason,
    int? confirmations,
    DateTime? paidAt,
    String? txRef,
  }) =>
      Invoice(
        id: id,
        dealId: dealId,
        payerUserId: payerUserId,
        payee: payee,
        kind: kind,
        amount: amount,
        status: status ?? this.status,
        statusReason: statusReason ?? this.statusReason,
        expiresAt: expiresAt,
        provider: provider,
        payAddress: payAddress,
        payUrl: payUrl,
        payAmount: payAmount,
        memo: memo,
        txRef: txRef ?? this.txRef,
        confirmations: confirmations ?? this.confirmations,
        paidAt: paidAt ?? this.paidAt,
        createdAt: createdAt,
      );

  factory Invoice.fromJson(Map<String, dynamic> j) {
    final now = DateTime.now().toUtc();
    return Invoice(
      id: (j['id'] ?? '').toString(),
      dealId: (j['deal_id'] ?? '').toString(),
      payerUserId: (j['payer_user_id'] ?? '').toString(),
      payee: (j['payee'] ?? '').toString(),
      kind: InvoiceKind.parse(j['kind']),
      amount: _money(j['amount']) ?? const Money(amount: '0', currency: 'USD'),
      status: InvoiceStatus.parse(j['status']),
      statusReason: _str(j['status_reason']),
      expiresAt: _date(j['expires_at']) ?? now,
      provider: (j['provider'] ?? '').toString(),
      payAddress: _str(j['pay_address']),
      payUrl: _str(j['pay_url']),
      payAmount: _money(j['pay_amount']),
      memo: (j['memo'] ?? '').toString(),
      txRef: _str(j['tx_ref']),
      confirmations: _int(j['confirmations']),
      paidAt: _date(j['paid_at']),
      createdAt: _date(j['created_at']) ?? now,
    );
  }
}

String? _str(Object? v) {
  if (v == null) return null;
  final s = v.toString();
  return s.isEmpty ? null : s;
}

int _int(Object? v) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse(v?.toString() ?? '') ?? 0;
}

DateTime? _date(Object? v) {
  if (v == null) return null;
  return DateTime.tryParse(v.toString())?.toUtc();
}

Money? _money(Object? v) {
  if (v is Map) return Money.fromJson(Map<String, dynamic>.from(v));
  return null;
}

/// Accepts a bare list or an `{items: [...]}` page; skips malformed rows.
List<Invoice> parseInvoiceList(Object? json) {
  Object? raw = json;
  if (json is Map) raw = json['items'];
  if (raw is! List) return const <Invoice>[];
  final out = <Invoice>[];
  for (final e in raw) {
    if (e is Map) out.add(Invoice.fromJson(Map<String, dynamic>.from(e)));
  }
  return out;
}

/// Time left until [expiresAt]; never negative.
Duration invoiceTimeLeft(DateTime expiresAt, DateTime now) {
  final d = expiresAt.difference(now);
  return d.isNegative ? Duration.zero : d;
}

/// `H:MM:SS` (hours may exceed 24).
String formatCountdown(Duration d) {
  final total = d.isNegative ? 0 : d.inSeconds;
  final h = total ~/ 3600;
  final m = (total % 3600) ~/ 60;
  final s = total % 60;
  String two(int n) => n.toString().padLeft(2, '0');
  return '$h:${two(m)}:${two(s)}';
}

/// i18n key for a friendly message for a payments failure
/// (404 not found, 409 wrong state, 503 provider off, ...).
String invoiceErrorKey(Object e) {
  if (e is ApiException) {
    switch (e.status) {
      case 401:
        return 'pay.err.auth';
      case 403:
        return 'pay.err.forbidden';
      case 404:
        return 'pay.err.not_found';
      case 409:
        return 'pay.err.conflict';
      case 422:
        return 'pay.err.invalid';
      case 503:
        return 'pay.err.provider_off';
    }
    if (e.code == 'timeout' || e.code == 'network_error') {
      return 'pay.err.network';
    }
  }
  return 'pay.err.generic';
}
