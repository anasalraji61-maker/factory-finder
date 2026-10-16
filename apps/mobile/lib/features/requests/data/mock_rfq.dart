import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';

/// Tab filter: `mine` = my requests, otherwise open requests of other buyers.
class RfqFilter {
  const RfqFilter({this.mine = true, this.status, this.kind});

  final bool mine;
  final RfqStatus? status;
  final ListingKind? kind;

  @override
  bool operator ==(Object other) =>
      other is RfqFilter &&
      other.mine == mine &&
      other.status == status &&
      other.kind == kind;

  @override
  int get hashCode => Object.hash(mine, status, kind);
}

/// Pure filter used by the mock repository (and tests).
List<RfqRequest> filterRequests(
  List<RfqRequest> all,
  RfqFilter f, {
  String userId = kMockUserId,
}) {
  return all.where((r) {
    final isMine = r.buyerId == userId;
    if (f.mine != isMine) return false;
    if (!f.mine && !r.isLive) return false;
    if (f.status != null && r.status != f.status) return false;
    if (f.kind != null && r.kind != f.kind) return false;
    return true;
  }).toList();
}

const Location _baghdad = Location(countryCode: 'IQ', city: 'Baghdad');

RfqRequest _req(
  String id,
  String buyer,
  String title,
  ListingKind kind,
  String qty,
  String unit,
  String? price,
  int offers, {
  RfqStatus status = RfqStatus.open,
  ItemCondition? cond,
  String? category,
  Location dest = _baghdad,
  String description = '',
  int day = 1,
  String cur = 'USD',
}) =>
    RfqRequest(
      id: id,
      buyerId: buyer,
      title: title,
      kind: kind,
      condition: cond,
      description: description,
      category: category,
      quantity: qty,
      unit: unit,
      targetPrice: price == null ? null : Money(amount: price, currency: cur),
      destination: dest,
      deadline: DateTime.utc(2026, 12, day + 10),
      status: status,
      offerCount: offers,
      createdAt: DateTime.utc(2026, 10, day),
    );

Offer _offer(
  String id,
  String reqId,
  String supId,
  String name,
  String cc,
  String city,
  String price,
  int moq,
  int lead,
  Incoterm inc,
  int trust,
  TrustBand band, {
  String cur = 'USD',
  String note = '',
  OfferStatus status = OfferStatus.active,
}) =>
    Offer(
      id: id,
      requestId: reqId,
      supplierId: supId,
      supplierName: name,
      supplierLocation: Location(countryCode: cc, city: city),
      trustScore: trust,
      trustBand: band,
      unitPrice: Money(amount: price, currency: cur),
      moq: moq,
      leadTimeDays: lead,
      incoterm: inc,
      validUntil: DateTime.utc(2026, 11, 30),
      note: note,
      status: status,
      createdAt: DateTime.utc(2026, 10, 5),
    );

List<RfqRequest> buildMockRequests() => [
      _req('req_001', kMockUserId, 'LED street lights 60W, solar', ListingKind.product, '200', 'piece', '42', 3,
          status: RfqStatus.negotiating, cond: ItemCondition.brandNew, category: 'lighting', description: 'IP66, 5-year warranty, with pole brackets.', day: 2),
      _req('req_002', kMockUserId, 'HDPE resin granules, film grade', ListingKind.rawMaterial, '40', 'ton', '1050', 2,
          status: RfqStatus.negotiating, category: 'plastics', description: 'MFI 0.9-1.2. Bulk shipment, container loads.', day: 3),
      _req('req_003', kMockUserId, 'Used PET bottle blowing line', ListingKind.productionLine, '1', 'line', '30000', 2,
          status: RfqStatus.negotiating, cond: ItemCondition.used, category: 'packaging', description: 'Capacity 6000 bph or more, 2020 or newer.', day: 4),
      _req('req_004', kMockUserId, 'Office chairs, ergonomic mesh', ListingKind.product, '120', 'piece', '50', 1,
          status: RfqStatus.awarded, category: 'furniture', day: 5),
      _req('req_005', 'usr_other1', 'Hot-rolled steel coil 3mm', ListingKind.rawMaterial, '100', 'ton', '540', 0,
          category: 'steel', dest: Location(countryCode: 'TR', city: 'Mersin'), day: 6),
      _req('req_006', 'usr_other2', 'Corrugated cartons, custom printed', ListingKind.product, '10000', 'piece', '0.45', 0,
          category: 'packaging', dest: Location(countryCode: 'AE', city: 'Dubai'), day: 7),
      _req('req_007', 'usr_other3', 'Refurbished bakery production line', ListingKind.productionLine, '1', 'line', '48000', 0,
          cond: ItemCondition.used, category: 'food_machinery', dest: Location(countryCode: 'EG', city: 'Cairo'), day: 8, cur: 'EUR'),
      _req('req_008', 'usr_other4', 'Plain cotton T-shirts, 180gsm', ListingKind.product, '5000', 'piece', '2.4', 0,
          category: 'apparel', dest: Location(countryCode: 'SA', city: 'Riyadh'), day: 9),
    ];

Map<String, List<Offer>> buildMockOffers() => {
      'req_001': [
        _offer('off_001', 'req_001', 'sup_101', 'Shenzhen BrightSolar Co.', 'CN', 'Shenzhen', '44.50', 100, 25, Incoterm.fob, 86, TrustBand.green, note: 'Price includes brackets.'),
        _offer('off_002', 'req_001', 'sup_102', 'Guangzhou LumaTech', 'CN', 'Guangzhou', '41.00', 200, 35, Incoterm.exw, 71, TrustBand.yellow),
        _offer('off_003', 'req_001', 'sup_103', 'Istanbul Aydinlatma', 'TR', 'Istanbul', '52.00', 50, 15, Incoterm.dap, 79, TrustBand.green, note: 'Delivered to Baghdad.'),
      ],
      'req_002': [
        _offer('off_004', 'req_002', 'sup_104', 'Ningbo PolyChem', 'CN', 'Ningbo', '1085', 20, 20, Incoterm.cfr, 82, TrustBand.green),
        _offer('off_005', 'req_002', 'sup_105', 'Jubail Petrochem Trading', 'SA', 'Jubail', '1120', 25, 14, Incoterm.fob, 74, TrustBand.yellow),
      ],
      'req_003': [
        _offer('off_006', 'req_003', 'sup_106', 'Foshan Machinery Exchange', 'CN', 'Foshan', '32500', 1, 30, Incoterm.fob, 68, TrustBand.yellow, note: 'Inspection video available.'),
        _offer('off_007', 'req_003', 'sup_107', 'Munich Used Lines GmbH', 'DE', 'Munich', '36800', 1, 45, Incoterm.exw, 88, TrustBand.green, cur: 'EUR'),
      ],
      'req_004': [
        _offer('off_008', 'req_004', 'sup_108', 'Foshan Comfort Furniture', 'CN', 'Foshan', '49.00', 100, 28, Incoterm.fob, 80, TrustBand.green, status: OfferStatus.accepted),
      ],
    };

/// Mutable in-memory backend behind the mock [RfqRepository].
class MockRfqBackend {
  MockRfqBackend()
      : requests = buildMockRequests(),
        offers = buildMockOffers();

  final List<RfqRequest> requests;
  final Map<String, List<Offer>> offers;
  int _seq = 100;

  /// Keyset-style paging over [filterRequests]. Cursor format `o:<offset>`
  /// (opaque to callers); malformed -> 422 `invalid_cursor` like the server.
  RfqPage listPage(RfqFilter f, {String? cursor, int pageSize = 50}) {
    final all = filterRequests(requests, f);
    var start = 0;
    if (cursor != null) {
      final parts = cursor.split(':');
      final n = parts.length == 2 && parts[0] == 'o' ? int.tryParse(parts[1]) : null;
      if (n == null || n < 0) {
        throw ApiException(
          status: 422,
          code: 'invalid_cursor',
          message: 'Malformed cursor',
        );
      }
      start = n > all.length ? all.length : n;
    }
    final size = pageSize < 1 ? 1 : pageSize;
    final end = start + size > all.length ? all.length : start + size;
    return RfqPage(
      items: all.sublist(start, end),
      total: all.length,
      page: 1,
      pageSize: size,
      nextCursor: end < all.length ? 'o:$end' : null,
    );
  }

  RfqRequest create(RfqDraft d, {String buyerId = kMockUserId}) {
    _seq++;
    final r = RfqRequest(
      id: 'req_$_seq',
      buyerId: buyerId,
      title: d.title,
      kind: d.kind,
      condition: d.condition,
      description: d.description,
      category: d.category,
      quantity: d.quantity,
      unit: d.unit,
      targetPrice: d.targetPrice,
      destination: d.destination,
      deadline: d.deadline,
      invitedSupplierIds: List<String>.of(d.invitedSupplierIds),
      createdAt: DateTime.now().toUtc(),
    );
    requests.insert(0, r);
    return r;
  }

  Offer? findOffer(String offerId) {
    for (final list in offers.values) {
      for (final o in list) {
        if (o.id == offerId) return o;
      }
    }
    return null;
  }

  List<Offer> myOffers(String requestId, {String userId = kMockUserId}) => [
        for (final o in offers[requestId] ?? const <Offer>[])
          if (o.supplierId == userId) o,
      ];

  /// Mirrors the server rules: 404 unknown request, 403 own request,
  /// 409 request not live or an active offer already exists.
  Offer submitOffer(
    String requestId,
    OfferDraft d, {
    String userId = kMockUserId,
  }) {
    final idx = requests.indexWhere((r) => r.id == requestId);
    if (idx < 0) {
      throw ApiException(status: 404, code: 'not_found', message: 'Request $requestId not found');
    }
    final req = requests[idx];
    if (req.buyerId == userId) {
      throw ApiException(status: 403, code: 'forbidden', message: 'Own request');
    }
    final mine = myOffers(requestId, userId: userId);
    if (!req.isLive || mine.any((o) => o.status == OfferStatus.active)) {
      throw ApiException(status: 409, code: 'conflict', message: 'Cannot offer');
    }
    _seq++;
    final offer = Offer(
      id: 'off_$_seq',
      requestId: requestId,
      supplierId: userId,
      supplierName: d.supplierName,
      unitPrice: d.price,
      moq: d.moq,
      leadTimeDays: d.leadTimeDays,
      note: d.note,
      createdAt: DateTime.now().toUtc(),
    );
    offers.putIfAbsent(requestId, () => <Offer>[]).add(offer);
    requests[idx] = req.copyWith(offerCount: req.offerCount + 1);
    return offer;
  }

  /// 404 unknown offer, 409 when the offer is no longer active.
  Offer withdrawOffer(String offerId) {
    for (final list in offers.values) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].id != offerId) continue;
        if (list[i].status != OfferStatus.active) {
          throw ApiException(status: 409, code: 'conflict', message: 'Offer not active');
        }
        list[i] = list[i].copyWith(status: OfferStatus.withdrawn);
        return list[i];
      }
    }
    throw ApiException(status: 404, code: 'not_found', message: 'Offer $offerId not found');
  }

  Deal accept(String offerId) {
    final offer = findOffer(offerId);
    if (offer == null) {
      throw StateError('offer not found');
    }
    final idx = requests.indexWhere((r) => r.id == offer.requestId);
    final req = requests[idx];
    final est = estimateDeal(req, offer);
    requests[idx] = req.copyWith(status: RfqStatus.awarded);
    final list = offers[offer.requestId]!;
    for (var i = 0; i < list.length; i++) {
      list[i] = list[i].copyWith(
        status: list[i].id == offerId ? OfferStatus.accepted : OfferStatus.rejected,
      );
    }
    _seq++;
    return Deal(
      id: 'deal_$_seq',
      requestId: req.id,
      offerId: offerId,
      quantity: req.quantity,
      unitPrice: offer.unitPrice,
      subtotal: est.goods,
      commission: est.commission,
      commissionRate: est.rate.toString(),
      minFeeApplied: est.minFee,
      isEstimate: true,
      supplierNet: est.net,
      createdAt: DateTime.now().toUtc(),
    );
  }
}
