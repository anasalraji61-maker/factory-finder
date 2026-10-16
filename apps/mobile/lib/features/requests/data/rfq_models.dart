import 'package:factory_finder/core/models/models.dart';

/// Reverse-marketplace models (hand-written JSON, see ARCHITECTURE §4 rfq).

/// A page of requests plus the keyset cursor for the next one
/// (`next_cursor` of GET /v1/requests; null on the last page).
class RfqPage extends PageResult<RfqRequest> {
  const RfqPage({
    required super.items,
    required super.total,
    required super.page,
    required super.pageSize,
    this.nextCursor,
  });

  final String? nextCursor;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  static RfqPage fromJson(Map<String, dynamic> j) {
    final base = PageResult.fromJson<RfqRequest>(j, RfqRequest.fromJson);
    final c = j['next_cursor'];
    return RfqPage(
      items: base.items,
      total: base.total,
      page: base.page,
      pageSize: base.pageSize,
      nextCursor: c is String && c.isNotEmpty ? c : null,
    );
  }
}

enum RfqStatus {
  open('open'),
  negotiating('negotiating'),
  awarded('awarded'),
  closed('closed'),
  cancelled('cancelled'),
  expired('expired');

  const RfqStatus(this.json);
  final String json;
}

RfqStatus rfqStatusFromJson(String? s) {
  if (s == 'accepted') return RfqStatus.awarded;
  for (final v in RfqStatus.values) {
    if (v.json == s) return v;
  }
  return RfqStatus.open;
}

enum OfferStatus {
  active('active'),
  accepted('accepted'),
  rejected('rejected'),
  withdrawn('withdrawn'),
  expired('expired');

  const OfferStatus(this.json);
  final String json;
}

OfferStatus offerStatusFromJson(String? s) {
  if (s == 'pending') return OfferStatus.active;
  for (final v in OfferStatus.values) {
    if (v.json == s) return v;
  }
  return OfferStatus.active;
}

Money? _moneyOrNull(Object? v) =>
    v is Map ? Money.fromJson(Map<String, dynamic>.from(v)) : null;

DateTime? _date(Object? v) => v == null ? null : DateTime.tryParse(v.toString());

String _iso(DateTime d) => d.toUtc().toIso8601String();

int? _intOrNull(Object? v) {
  if (v is num) return v.toInt();
  return int.tryParse(v?.toString() ?? '');
}

/// `lead_time_days` may be an int or a {min,max} range: returns the max.
int? _leadDays(Object? v) {
  if (v is Map) return _intOrNull(v['max'] ?? v['min']);
  return _intOrNull(v);
}

/// Max invited suppliers on one request (contracts/openapi/rfq.yaml).
const int kRfqMaxInvites = 50;

final RegExp _supplierIdPattern = RegExp(r'^[A-Za-z0-9_.:-]{1,64}$');

/// True when [id] is acceptable as an `invited_supplier_ids` entry.
bool isValidInviteId(String id) => _supplierIdPattern.hasMatch(id);

/// A supplier picked as an invitee (only [id] is sent to the backend).
class InvitedSupplier {
  const InvitedSupplier({required this.id, required this.name});

  final String id;
  final String name;
}

List<String> _stringList(Object? v) {
  if (v is! List) return const <String>[];
  final out = <String>[];
  for (final e in v) {
    final s = e?.toString() ?? '';
    if (s.isNotEmpty && !out.contains(s)) out.add(s);
  }
  return out;
}

class RfqRequest {
  const RfqRequest({
    required this.id,
    required this.title,
    required this.kind,
    required this.quantity,
    required this.createdAt,
    this.buyerId,
    this.condition,
    this.description = '',
    this.category,
    this.unit = 'piece',
    this.targetPrice,
    this.destination,
    this.deadline,
    this.status = RfqStatus.open,
    this.offerCount = 0,
    this.invitedSupplierIds = const <String>[],
  });

  final String id;
  final String? buyerId;
  final String title;
  final ListingKind kind;
  final ItemCondition? condition;
  final String description;
  final String? category;

  /// Decimal string.
  final String quantity;
  final String unit;

  /// Target unit price.
  final Money? targetPrice;
  final Location? destination;
  final DateTime? deadline;
  final RfqStatus status;
  final int offerCount;
  final DateTime createdAt;

  /// Invite-only request: only these suppliers can see it. Echoed by the
  /// backend in the buyer's own views only; empty otherwise.
  final List<String> invitedSupplierIds;

  bool get isInviteOnly => invitedSupplierIds.isNotEmpty;

  /// Open or negotiating: can still receive / accept offers.
  bool get isLive =>
      status == RfqStatus.open || status == RfqStatus.negotiating;

  double get quantityValue => double.tryParse(quantity) ?? 0;

  RfqRequest copyWith({RfqStatus? status, int? offerCount}) => RfqRequest(
        id: id,
        buyerId: buyerId,
        title: title,
        kind: kind,
        condition: condition,
        description: description,
        category: category,
        quantity: quantity,
        unit: unit,
        targetPrice: targetPrice,
        destination: destination,
        deadline: deadline,
        status: status ?? this.status,
        offerCount: offerCount ?? this.offerCount,
        createdAt: createdAt,
        invitedSupplierIds: invitedSupplierIds,
      );

  factory RfqRequest.fromJson(Map<String, dynamic> j) {
    final dest = j['destination'];
    final cond = j['condition'] as String?;
    return RfqRequest(
      id: j['id'].toString(),
      buyerId: (j['owner_id'] ?? j['buyer_id'])?.toString(),
      title: (j['title'] as String?) ?? '',
      kind: listingKindFromJson((j['kind'] as String?) ?? 'product'),
      condition: (cond == null || cond == 'any')
          ? null
          : itemConditionFromJson(cond),
      description: (j['description'] as String?) ?? '',
      category: j['category'] as String?,
      quantity: (j['quantity'] ?? '1').toString(),
      unit: (j['unit'] as String?) ?? 'piece',
      targetPrice: _moneyOrNull(j['target_price']),
      destination: dest is Map
          ? Location.fromJson(Map<String, dynamic>.from(dest))
          : null,
      deadline: _date(j['deadline']),
      status: rfqStatusFromJson(j['status'] as String?),
      offerCount: _intOrNull(j['offers_count'] ?? j['offer_count']) ?? 0,
      createdAt: _date(j['created_at']) ?? DateTime.now().toUtc(),
      invitedSupplierIds: _stringList(j['invited_supplier_ids']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        if (buyerId != null) 'owner_id': buyerId,
        'title': title,
        'kind': kind.json,
        if (condition != null) 'condition': condition!.json,
        'description': description,
        if (category != null) 'category': category,
        'quantity': quantity,
        'unit': unit,
        if (targetPrice != null) 'target_price': targetPrice!.toJson(),
        if (destination != null) 'destination': destination!.toJson(),
        if (deadline != null) 'deadline': _iso(deadline!),
        'status': status.json,
        'offers_count': offerCount,
        'created_at': _iso(createdAt),
        if (invitedSupplierIds.isNotEmpty)
          'invited_supplier_ids': invitedSupplierIds,
      };
}

/// Body of POST /v1/requests.
class RfqDraft {
  const RfqDraft({
    required this.kind,
    required this.title,
    required this.quantity,
    required this.unit,
    required this.destination,
    this.condition,
    this.description = '',
    this.category,
    this.targetPrice,
    this.deadline,
    this.invitedSupplierIds = const <String>[],
  });

  final ListingKind kind;
  final ItemCondition? condition;
  final String title;
  final String description;
  final String? category;
  final String quantity;
  final String unit;
  final Money? targetPrice;
  final Location destination;
  final DateTime? deadline;

  /// Optional invite-only list (max [kRfqMaxInvites]); omitted when empty.
  final List<String> invitedSupplierIds;

  Map<String, dynamic> toJson() => {
        'kind': kind.json,
        if (condition != null) 'condition': condition!.json,
        'title': title,
        if (description.isNotEmpty) 'description': description,
        'quantity': quantity,
        'unit': unit,
        if (targetPrice != null) 'target_price': targetPrice!.toJson(),
        'destination': destination.toJson(),
        if (deadline != null) 'deadline': _iso(deadline!),
        if (invitedSupplierIds.isNotEmpty)
          'invited_supplier_ids': invitedSupplierIds,
      };
}

class Offer {
  const Offer({
    required this.id,
    required this.requestId,
    required this.supplierName,
    required this.unitPrice,
    required this.createdAt,
    this.supplierId,
    this.supplierLocation,
    this.trustScore,
    this.trustBand = TrustBand.unknown,
    this.moq,
    this.leadTimeDays,
    this.incoterm,
    this.validUntil,
    this.note = '',
    this.status = OfferStatus.active,
  });

  final String id;
  final String requestId;
  final String? supplierId;
  final String supplierName;
  final Location? supplierLocation;
  final int? trustScore;
  final TrustBand trustBand;
  final Money unitPrice;
  final int? moq;
  final int? leadTimeDays;
  final Incoterm? incoterm;
  final DateTime? validUntil;
  final String note;
  final OfferStatus status;
  final DateTime createdAt;

  Offer copyWith({OfferStatus? status}) => Offer(
        id: id,
        requestId: requestId,
        supplierId: supplierId,
        supplierName: supplierName,
        supplierLocation: supplierLocation,
        trustScore: trustScore,
        trustBand: trustBand,
        unitPrice: unitPrice,
        moq: moq,
        leadTimeDays: leadTimeDays,
        incoterm: incoterm,
        validUntil: validUntil,
        note: note,
        status: status ?? this.status,
        createdAt: createdAt,
      );

  factory Offer.fromJson(Map<String, dynamic> j) {
    final sup = j['supplier'] is Map
        ? Map<String, dynamic>.from(j['supplier'] as Map)
        : <String, dynamic>{};
    final loc = j['supplier_location'] ?? sup['location'];
    final inc = j['incoterm'] as String?;
    return Offer(
      id: j['id'].toString(),
      requestId: (j['request_id'] ?? '').toString(),
      supplierId: (j['supplier_ref'] ?? j['supplier_id'] ?? sup['id'])?.toString(),
      supplierName: (j['supplier_name'] ?? sup['name'] ?? '').toString(),
      supplierLocation: loc is Map
          ? Location.fromJson(Map<String, dynamic>.from(loc))
          : null,
      trustScore: _intOrNull(j['trust_score'] ?? sup['trust_score']),
      trustBand: trustBandFromJson(
        (j['trust_band'] ?? sup['trust_band'])?.toString() ?? '',
      ),
      unitPrice: _moneyOrNull(j['price'] ?? j['unit_price']) ??
          const Money(amount: '0', currency: 'USD'),
      moq: _intOrNull(j['moq']),
      leadTimeDays: _leadDays(j['lead_time_days']),
      incoterm: inc == null ? null : incotermFromJson(inc),
      validUntil: _date(j['valid_until']),
      note: ((j['notes'] ?? j['note']) as String?) ?? '',
      status: offerStatusFromJson(j['status'] as String?),
      createdAt: _date(j['created_at']) ?? DateTime.now().toUtc(),
    );
  }

  /// Contract shape (OfferCreate + id/request_id/status); trust and location
  /// are optional client-side extras.
  Map<String, dynamic> toJson() => {
        'id': id,
        'request_id': requestId,
        if (supplierId != null) 'supplier_ref': supplierId,
        'supplier_name': supplierName,
        if (supplierLocation != null) 'supplier_location': supplierLocation!.toJson(),
        if (trustScore != null) 'trust_score': trustScore,
        'trust_band': trustBand.json,
        'price': unitPrice.toJson(),
        if (moq != null) 'moq': moq,
        if (leadTimeDays != null) 'lead_time_days': leadTimeDays,
        if (incoterm != null) 'incoterm': incoterm!.json,
        if (validUntil != null) 'valid_until': _iso(validUntil!),
        'notes': note,
        'status': status.json,
        'created_at': _iso(createdAt),
      };
}

/// Body of POST /v1/requests/{id}/offers (OfferCreate). The price is a
/// decimal string; optional fields are omitted when null / empty.
class OfferDraft {
  const OfferDraft({
    required this.price,
    required this.supplierName,
    this.moq,
    this.leadTimeDays,
    this.note = '',
  });

  final Money price;
  final String supplierName;
  final int? moq;
  final int? leadTimeDays;
  final String note;

  Map<String, dynamic> toJson() => {
        'price': price.toJson(),
        'supplier_name': supplierName,
        if (moq != null) 'moq': moq,
        if (leadTimeDays != null) 'lead_time_days': leadTimeDays,
        if (note.isNotEmpty) 'notes': note,
      };
}

/// Per-invoice-kind payment state of a deal (`null` = no invoice reported yet).
class DealPayment {
  const DealPayment({this.commission, this.dealPayment});

  /// `open`, `paid`, `refunded` or null.
  final String? commission;
  final String? dealPayment;

  static const DealPayment none = DealPayment();

  factory DealPayment.fromJson(Object? json) {
    if (json is! Map) return none;
    String? v(Object? x) => x is String && x.isNotEmpty ? x : null;
    return DealPayment(
      commission: v(json['commission']),
      dealPayment: v(json['deal_payment']),
    );
  }

  Map<String, dynamic> toJson() => {
        'commission': commission,
        'deal_payment': dealPayment,
      };
}

class Deal {
  const Deal({
    required this.id,
    required this.requestId,
    required this.offerId,
    required this.subtotal,
    required this.commission,
    required this.createdAt,
    this.commissionRate,
    this.minFeeApplied = false,
    this.isEstimate = false,
    this.supplierNet,
    this.quantity,
    this.unitPrice,
    this.status = 'pending_payment',
    this.buyerId,
    this.supplierUserId,
    this.payment = DealPayment.none,
    this.deliveredAt,
    this.completedAt,
  });

  final String id;
  final String requestId;
  final String offerId;

  /// Goods value (quantity x unit price).
  final Money subtotal;

  /// Commission amount.
  final Money commission;

  /// Decimal fraction string, e.g. "0.03".
  final String? commissionRate;
  final bool minFeeApplied;
  final bool isEstimate;
  final Money? supplierNet;
  final String? quantity;
  final Money? unitPrice;
  final String status;
  final DateTime createdAt;
  final String? buyerId;
  final String? supplierUserId;
  final DealPayment payment;
  final DateTime? deliveredAt;
  final DateTime? completedAt;

  Deal copyWith({
    String? status,
    DealPayment? payment,
    DateTime? deliveredAt,
    DateTime? completedAt,
  }) =>
      Deal(
        id: id,
        requestId: requestId,
        offerId: offerId,
        subtotal: subtotal,
        commission: commission,
        createdAt: createdAt,
        commissionRate: commissionRate,
        minFeeApplied: minFeeApplied,
        isEstimate: isEstimate,
        supplierNet: supplierNet,
        quantity: quantity,
        unitPrice: unitPrice,
        status: status ?? this.status,
        buyerId: buyerId,
        supplierUserId: supplierUserId,
        payment: payment ?? this.payment,
        deliveredAt: deliveredAt ?? this.deliveredAt,
        completedAt: completedAt ?? this.completedAt,
      );

  factory Deal.fromJson(Map<String, dynamic> j) {
    final subtotal = _moneyOrNull(j['subtotal'] ?? j['goods_total']) ??
        const Money(amount: '0', currency: 'USD');
    final c = j['commission'];
    Money commission = Money(amount: '0', currency: subtotal.currency);
    String? rate = j['commission_rate']?.toString();
    var minFee = false;
    var estimate = false;
    if (c is Map) {
      final cm = Map<String, dynamic>.from(c);
      if (cm['amount'] is Map) {
        commission = Money.fromJson(Map<String, dynamic>.from(cm['amount'] as Map));
      } else if (cm['currency'] != null) {
        commission = Money.fromJson(cm);
      }
      rate = cm['rate']?.toString() ?? rate;
      minFee = (cm['min_fee_applied'] as bool?) ?? false;
      estimate = (cm['is_estimate'] as bool?) ?? false;
    }
    return Deal(
      id: j['id'].toString(),
      requestId: (j['request_id'] ?? '').toString(),
      offerId: (j['offer_id'] ?? '').toString(),
      subtotal: subtotal,
      commission: commission,
      commissionRate: rate,
      minFeeApplied: minFee,
      isEstimate: estimate,
      supplierNet: _moneyOrNull(j['supplier_net']),
      quantity: j['quantity']?.toString(),
      unitPrice: _moneyOrNull(j['unit_price']),
      status: (j['status'] as String?) ?? 'pending_payment',
      createdAt: _date(j['created_at']) ?? DateTime.now().toUtc(),
      buyerId: j['buyer_id']?.toString(),
      supplierUserId: j['supplier_user_id']?.toString(),
      payment: DealPayment.fromJson(j['payment']),
      deliveredAt: _date(j['delivered_at']),
      completedAt: _date(j['completed_at']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'request_id': requestId,
        'offer_id': offerId,
        if (buyerId != null) 'buyer_id': buyerId,
        if (supplierUserId != null) 'supplier_user_id': supplierUserId,
        'payment': payment.toJson(),
        'delivered_at': deliveredAt == null ? null : _iso(deliveredAt!),
        'completed_at': completedAt == null ? null : _iso(completedAt!),
        if (quantity != null) 'quantity': quantity,
        if (unitPrice != null) 'unit_price': unitPrice!.toJson(),
        'subtotal': subtotal.toJson(),
        'commission': {
          if (commissionRate != null) 'rate': commissionRate,
          'amount': commission.toJson(),
          'min_fee_applied': minFeeApplied,
          'is_estimate': isEstimate,
        },
        if (supplierNet != null) 'supplier_net': supplierNet!.toJson(),
        'status': status,
        'created_at': _iso(createdAt),
      };
}

/// Commission rate by listing kind (rfq contract) and the minimum fee in USD.
const Map<ListingKind, double> kCommissionRates = {
  ListingKind.product: 0.03,
  ListingKind.rawMaterial: 0.02,
  ListingKind.productionLine: 0.04,
};
const double kMinCommissionUsd = 25;

/// Estimated deal amounts for [offer] on [request] (quantity x unit price).
/// The server computes the real commission; this is only a preview.
({Money goods, Money commission, Money net, double rate, bool minFee}) estimateDeal(
  RfqRequest request,
  Offer offer,
) {
  final rate = kCommissionRates[request.kind] ?? 0.03;
  final cur = offer.unitPrice.currency;
  final goods = offer.unitPrice.value * request.quantityValue;
  var fee = goods * rate;
  var minFee = false;
  if (cur == 'USD' && fee < kMinCommissionUsd) {
    fee = kMinCommissionUsd;
    minFee = true;
  }
  return (
    goods: Money(amount: goods.toStringAsFixed(2), currency: cur),
    commission: Money(amount: fee.toStringAsFixed(2), currency: cur),
    net: Money(amount: (goods - fee).toStringAsFixed(2), currency: cur),
    rate: rate,
    minFee: minFee,
  );
}
