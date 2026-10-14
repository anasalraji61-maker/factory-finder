import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';

/// Deal statuses (rfq contract `DealStatus`).
const String kDealPendingPayment = 'pending_payment';
const String kDealPaid = 'paid';
const String kDealInFulfilment = 'in_fulfilment';
const String kDealCompleted = 'completed';

/// Who the signed-in user is on a deal. [both] is the mock-mode demo role.
enum DealRole { buyer, supplier, both, none }

/// [demo] (mock mode) grants both roles; [assumeBuyer] is the request owner.
DealRole dealRoleFor(
  Deal deal,
  String? myId, {
  bool demo = false,
  bool assumeBuyer = false,
}) {
  if (demo) return DealRole.both;
  final isBuyer = assumeBuyer || (myId != null && deal.buyerId == myId);
  final isSupplier = myId != null && deal.supplierUserId == myId;
  if (isBuyer && isSupplier) return DealRole.both;
  if (isBuyer) return DealRole.buyer;
  if (isSupplier) return DealRole.supplier;
  return DealRole.none;
}

extension DealRoleX on DealRole {
  bool get isBuyer => this == DealRole.buyer || this == DealRole.both;
  bool get isSupplier => this == DealRole.supplier || this == DealRole.both;
}

/// Which lifecycle actions the [role] may take right now.
class DealActions {
  const DealActions({
    this.startFulfilment = false,
    this.markDelivered = false,
    this.confirmReceipt = false,
  });

  final bool startFulfilment;
  final bool markDelivered;
  final bool confirmReceipt;

  bool get any => startFulfilment || markDelivered || confirmReceipt;
}

DealActions dealActionsFor(Deal deal, DealRole role) => DealActions(
      startFulfilment: role.isSupplier && deal.status == kDealPaid,
      markDelivered: role.isSupplier &&
          deal.status == kDealInFulfilment &&
          deal.deliveredAt == null,
      confirmReceipt: role.isBuyer && deal.status == kDealInFulfilment,
    );

/// One row of `GET /v1/deals/{id}/events`.
class DealEvent {
  const DealEvent({
    required this.seq,
    required this.action,
    required this.actorRole,
    this.fromStatus,
    this.toStatus,
    this.data = const <String, dynamic>{},
    this.createdAt,
  });

  final int seq;

  /// payment_paid, payment_refunded, fulfilment_started, delivered,
  /// receipt_confirmed (unknown values are kept as-is).
  final String action;

  /// buyer, supplier or system.
  final String actorRole;
  final String? fromStatus;
  final String? toStatus;
  final Map<String, dynamic> data;
  final DateTime? createdAt;

  factory DealEvent.fromJson(Map<String, dynamic> j) {
    final seq = j['seq'];
    final data = j['data'];
    final created = j['created_at'];
    String? str(Object? v) => v is String && v.isNotEmpty ? v : null;
    return DealEvent(
      seq: seq is num ? seq.toInt() : int.tryParse('$seq') ?? 0,
      action: (j['action'] ?? '').toString(),
      actorRole: (j['actor_role'] ?? 'system').toString(),
      fromStatus: str(j['from_status']),
      toStatus: str(j['to_status']),
      data: data is Map ? Map<String, dynamic>.from(data) : <String, dynamic>{},
      createdAt: created is String ? DateTime.tryParse(created) : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'seq': seq,
        'action': action,
        'actor_role': actorRole,
        'from_status': fromStatus,
        'to_status': toStatus,
        'data': data,
        'created_at': createdAt?.toUtc().toIso8601String(),
      };
}

class DealEventList {
  const DealEventList({required this.items, required this.total});

  final List<DealEvent> items;
  final int total;

  static const DealEventList empty = DealEventList(items: <DealEvent>[], total: 0);

  factory DealEventList.fromJson(Object? json) {
    if (json is! Map) return empty;
    final raw = json['items'];
    final items = <DealEvent>[
      if (raw is List)
        for (final e in raw)
          if (e is Map) DealEvent.fromJson(Map<String, dynamic>.from(e)),
    ]..sort((a, b) => a.seq.compareTo(b.seq));
    final total = json['total'];
    return DealEventList(
      items: items,
      total: total is num ? total.toInt() : items.length,
    );
  }
}

/// i18n key for a failed deal-lifecycle call.
String dealErrorKey(Object e) {
  if (e is! ApiException) return 'deals.err.generic';
  switch (e.code) {
    case 'invalid_deal_transition':
      return 'deals.err.invalid_deal_transition';
    case 'supplier_verification_required':
      return 'deals.err.supplier_verification_required';
    case 'timeout':
    case 'network_error':
      return 'deals.err.network';
  }
  switch (e.status) {
    case 401:
      return 'deals.err.auth';
    case 403:
      return 'deals.err.forbidden';
    case 404:
      return 'deals.err.not_found';
    case 409:
      return 'deals.err.invalid_deal_transition';
    case 429:
      return 'deals.err.rate_limited';
  }
  return 'deals.err.generic';
}
