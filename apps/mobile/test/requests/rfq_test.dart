import 'dart:convert';

import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_validators.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _roundTrip(Map<String, dynamic> j) =>
    jsonDecode(jsonEncode(j)) as Map<String, dynamic>;

void main() {
  group('models', () {
    test('RfqRequest round trip', () {
      for (final r in buildMockRequests()) {
        final json = _roundTrip(r.toJson());
        expect(RfqRequest.fromJson(json).toJson(), json);
      }
    });

    test('Offer round trip', () {
      for (final list in buildMockOffers().values) {
        for (final o in list) {
          final json = _roundTrip(o.toJson());
          expect(Offer.fromJson(json).toJson(), json);
        }
      }
    });

    test('Deal round trip', () {
      final deal = Deal(
        id: 'deal_1',
        requestId: 'req_1',
        offerId: 'off_1',
        quantity: '100',
        unitPrice: const Money(amount: '10.00', currency: 'USD'),
        subtotal: const Money(amount: '1000.00', currency: 'USD'),
        commission: const Money(amount: '30.00', currency: 'USD'),
        commissionRate: '0.03',
        supplierNet: const Money(amount: '970.00', currency: 'USD'),
        createdAt: DateTime.utc(2026, 10, 13),
      );
      final json = _roundTrip(deal.toJson());
      expect(Deal.fromJson(json).toJson(), json);
    });

    test('tolerates missing optional fields and alternative shapes', () {
      final r = RfqRequest.fromJson({'id': 'req_x', 'title': 'T', 'quantity': 5});
      expect(r.status, RfqStatus.open);
      expect(r.kind, ListingKind.product);
      expect(r.condition, isNull);
      expect(r.quantity, '5');

      final o = Offer.fromJson({
        'id': 'off_x',
        'request_id': 'req_x',
        'unit_price': {'amount': 3, 'currency': 'EUR'},
        'lead_time_days': {'min': 10, 'max': 20},
        'supplier': {'id': 'sup_1', 'name': 'ACME'},
      });
      expect(o.supplierName, 'ACME');
      expect(o.supplierId, 'sup_1');
      expect(o.leadTimeDays, 20);
      expect(o.unitPrice.amount, '3');
      expect(rfqStatusFromJson('accepted'), RfqStatus.awarded);
    });

    test('draft JSON follows the create contract', () {
      const draft = RfqDraft(
        kind: ListingKind.rawMaterial,
        condition: ItemCondition.used,
        title: 'Resin',
        quantity: '40',
        unit: 'ton',
        targetPrice: Money(amount: '1050', currency: 'USD'),
        destination: Location(countryCode: 'IQ', city: 'Baghdad'),
      );
      final j = draft.toJson();
      expect(j['kind'], 'raw_material');
      expect(j['condition'], 'used');
      expect(j['quantity'], '40');
      expect(j['target_price'], {'amount': '1050', 'currency': 'USD'});
      expect(j['destination'], {'country_code': 'IQ', 'city': 'Baghdad'});
      expect(j.containsKey('deadline'), isFalse);
    });

    test('estimateDeal multiplies unit price by quantity and adds commission', () {
      final req = buildMockRequests().first; // quantity 200
      final offer = buildMockOffers()[req.id]!.first; // 44.50
      final est = estimateDeal(req, offer);
      expect(est.goods.amount, '8900.00');
      expect(est.rate, 0.03);
      expect(est.commission.amount, '267.00');
      expect(est.net.amount, '8633.00');
      expect(est.minFee, isFalse);
    });

    test('estimateDeal applies the 25 USD minimum fee', () {
      final req = buildMockRequests().firstWhere((r) => r.id == 'req_006');
      final offer = Offer.fromJson({
        'id': 'off_t',
        'request_id': req.id,
        'price': {'amount': '0.10', 'currency': 'USD'},
      });
      final est = estimateDeal(req, offer); // 10000 pieces x 0.10 = 1000 -> 3% = 30
      expect(est.commission.amount, '30.00');
      final small = estimateDeal(
        req.copyWith(),
        Offer.fromJson({
          'id': 'off_u',
          'request_id': req.id,
          'price': {'amount': '0.01', 'currency': 'USD'},
        }),
      ); // 100 USD -> 3 -> min 25
      expect(small.commission.amount, '25.00');
      expect(small.minFee, isTrue);
    });
  });

  group('mock repository data', () {
    test('has at least 6 requests, some with offers', () {
      final reqs = buildMockRequests();
      expect(reqs.length, greaterThanOrEqualTo(6));
      expect(reqs.map((r) => r.id).toSet().length, reqs.length);
      final offers = buildMockOffers();
      expect(offers.keys.length, greaterThanOrEqualTo(4));
      expect(offers.values.expand((e) => e).length, greaterThanOrEqualTo(6));
    });

    test('filters: mine vs open', () {
      final all = buildMockRequests();
      final mine = filterRequests(all, const RfqFilter(mine: true));
      expect(mine, isNotEmpty);
      expect(mine.every((r) => r.buyerId == kMockUserId), isTrue);

      final open = filterRequests(
        all,
        const RfqFilter(mine: false, status: RfqStatus.open),
      );
      expect(open, isNotEmpty);
      expect(open.every((r) => r.buyerId != kMockUserId), isTrue);
      expect(open.every((r) => r.isLive), isTrue);

      final lines = filterRequests(
        all,
        const RfqFilter(mine: true, kind: ListingKind.productionLine),
      );
      expect(lines.every((r) => r.kind == ListingKind.productionLine), isTrue);

      final awarded = filterRequests(
        all,
        const RfqFilter(mine: true, status: RfqStatus.awarded),
      );
      expect(awarded.length, 1);
    });

    test('backend create and accept', () {
      final b = MockRfqBackend();
      final created = b.create(
        const RfqDraft(
          kind: ListingKind.product,
          title: 'Test',
          quantity: '10',
          unit: 'piece',
          destination: Location(countryCode: 'IQ'),
        ),
      );
      expect(b.requests.first.id, created.id);
      expect(created.status, RfqStatus.open);

      final deal = b.accept('off_001');
      expect(deal.subtotal.amount, '8900.00');
      expect(deal.commission.amount, '267.00');
      expect(deal.supplierNet!.amount, '8633.00');
      expect(b.requests.firstWhere((r) => r.id == 'req_001').status, RfqStatus.awarded);
      final statuses = b.offers['req_001']!.map((o) => o.status).toList();
      expect(statuses.where((s) => s == OfferStatus.accepted).length, 1);
      expect(statuses.where((s) => s == OfferStatus.rejected).length, 2);
    });
  });

  group('validators', () {
    test('title', () {
      expect(validateRfqTitle(''), 'req.err.title_required');
      expect(validateRfqTitle('ab'), 'req.err.title_short');
      expect(validateRfqTitle('Steel coil'), isNull);
    });

    test('quantity', () {
      expect(validateRfqQuantity(null), 'req.err.qty_required');
      expect(validateRfqQuantity('0'), 'req.err.qty_invalid');
      expect(validateRfqQuantity('abc'), 'req.err.qty_invalid');
      expect(validateRfqQuantity('12.5'), isNull);
    });

    test('target price is optional', () {
      expect(validateRfqTargetPrice(''), isNull);
      expect(validateRfqTargetPrice('-3'), 'req.err.price_invalid');
      expect(validateRfqTargetPrice('42'), isNull);
    });

    test('deadline', () {
      final today = DateTime(2026, 10, 13);
      expect(validateRfqDeadline(null, today), isNull);
      expect(validateRfqDeadline(DateTime(2026, 10, 12), today), 'req.err.deadline_past');
      expect(validateRfqDeadline(DateTime(2026, 10, 13), today), isNull);
      expect(validateRfqDeadline(DateTime(2026, 11, 1), today), isNull);
    });

    test('normalizeNumberInput handles Arabic digits and comma decimals', () {
      expect(normalizeNumberInput('١٢٣'), '123');
      expect(normalizeNumberInput('4,5'), '4.5');
      expect(normalizeNumberInput(' 7٫25 '), '7.25');
    });
  });
}
