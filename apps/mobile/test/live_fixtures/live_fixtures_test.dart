import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:flutter_test/flutter_test.dart';

/// Real gateway responses saved from a local run of the services
/// (test/fixtures/live/*.json). They protect the Dart parsers from drift.
dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

Map<String, dynamic> _obj(String name) =>
    Map<String, dynamic>.from(_load(name) as Map);

const String _myId = 'usr_21403c1febf04074ad43675c33496143';

void main() {
  group('discover', () {
    test('search page + listing', () {
      final page = PageResult.fromJson<Listing>(_obj('search'), Listing.fromJson);
      expect(page.total, 2);
      expect(page.page, 1);
      expect(page.items, hasLength(2));
      final l = page.items.first;
      expect(l.id, 'lst_0041');
      expect(l.kind, ListingKind.product);
      expect(l.condition, ItemCondition.brandNew);
      expect(l.price.min.amount, '3.00');
      expect(l.price.max.currency, 'USD');
      expect(l.incoterm, Incoterm.fob);
      expect(l.moq, 500);
      expect(l.leadTimeDays?.max, 20);
      expect(l.supplier.id, 'sup_cn_018');
      expect(l.supplier.trustBand, TrustBand.green);
      expect(l.supplier.trustScore, 91);
      expect(l.origin?.countryCode, 'CN');
      expect(l.titleAr, isNotEmpty);
    });

    test('listing detail, supplier, trust', () {
      final l = Listing.fromJson(_obj('listing'));
      expect(l.hsCode, '9405.42');
      expect(l.unitWeightKg, 3.2);
      final s = SupplierSummary.fromJson(_obj('supplier'));
      expect(s.id, 'sup_cn_018');
      expect(s.verified, isTrue);
      expect(s.yearsInBusiness, 10);
      final t = TrustScore.fromJson(_obj('trust'));
      expect(t.supplierId, 'sup_cn_018');
      expect(t.score, 91);
      expect(t.band, TrustBand.green);
      expect(t.factors, isNotEmpty);
      expect(t.factors.first.key, 'years_in_business');
      expect(t.factors.first.explanationAr, isNotNull);
    });

    test('categories tree and the chip -> slug map', () {
      final nodes = [
        for (final e in _load('categories') as List)
          CategoryNode.fromJson(Map<String, dynamic>.from(e as Map)),
      ];
      expect(nodes.map((n) => n.slug),
          ['product', 'raw_material', 'production_line']);
      final real = <String>{
        for (final n in nodes) ...n.children.map((c) => c.slug),
      };
      for (final entry in kLiveCategorySlugs.entries) {
        if (entry.value != null) {
          expect(real, contains(entry.value), reason: entry.key);
        }
      }
      for (final keys in kCategoriesByKind.values) {
        for (final k in keys) {
          expect(kLiveCategorySlugs.containsKey(k), isTrue, reason: k);
        }
      }
    });
  });

  group('auth', () {
    test('register / login responses carry a nested user', () {
      for (final name in ['auth_register', 'auth_login']) {
        final j = _obj(name);
        expect(j['access_token'], isA<String>());
        expect(j['refresh_token'], isA<String>());
        final me = Me.fromJson(Map<String, dynamic>.from(j['user'] as Map));
        expect(me.id, _myId);
        expect(me.role, 'buyer');
      }
    });

    test('refresh response has tokens and a null user', () {
      final j = _obj('auth_refresh');
      expect(j['access_token'], isA<String>());
      expect(j['user'], isNull);
    });

    test('GET /v1/me', () {
      final me = Me.fromJson(_obj('me'));
      expect(me.id, _myId);
      expect(me.displayCurrency, 'USD');
      expect(me.language, 'ar');
      expect(me.defaultDestination, isNull);
    });

    test('error bodies map to ApiException', () {
      for (final entry in {
        'error_404': [404, 'listing_not_found'],
        'error_login': [401, 'invalid_credentials'],
        'error_refresh_throttled': [429, 'refresh_throttled'],
        'error_invalid_deal_transition': [409, 'invalid_deal_transition'],
        'error_supplier_verification_required': [403, 'supplier_verification_required'],
        'error_report_own_listing': [409, 'own_listing'],
        'error_report_rate_limited': [429, 'rate_limited'],
      }.entries) {
        final ro = RequestOptions(path: '/x');
        final e = mapDioError(DioException(
          requestOptions: ro,
          response: Response<dynamic>(
            requestOptions: ro,
            statusCode: entry.value[0] as int,
            data: _load(entry.key),
          ),
          type: DioExceptionType.badResponse,
        ));
        expect(e.status, entry.value[0]);
        expect(e.code, entry.value[1]);
        expect(e.message, isNotEmpty);
      }
    });
  });

  group('logistics', () {
    test('landed-cost quote', () {
      final q = LandedCostQuote.fromJson(_obj('quote'));
      expect(q.currency, 'USD');
      expect(q.destination?.countryCode, 'IQ');
      expect(q.options, hasLength(7));
      expect(q.createdAt.year, 2026);
      final o = q.options.first;
      expect(o.mode, TransportMode.seaLcl);
      expect(o.recommended, isTrue);
      expect(o.total.max.amount, '5852.29');
      expect(o.transitDays.max, 63);
      expect(o.co2Kg, 305.4);
      expect(o.lines.first.stage, 'goods');
      expect(o.lines.first.estimate, isFalse);
      expect(o.lines.first.fxRate, '1');
      expect(o.lines.any((l) => l.stage == 'duties'), isTrue);
      expect(q.options.where((e) => e.warnings.isNotEmpty), isNotEmpty);
      expect(q.assumptions, isNotEmpty);
    });

    test('request body only has contract keys', () {
      const r = QuoteRequest(
        goodsValue: 2750,
        weightKg: 1600,
        volumeM3: 10,
        origin: Location(countryCode: 'CN', city: 'Shenzhen'),
        destination: Location(countryCode: 'IQ', city: 'Baghdad'),
        hsCode: '940542',
        modes: {TransportMode.air},
      );
      final j = r.toJson();
      expect(j.keys.toSet(), {
        'goods',
        'origin',
        'destination',
        'supplier_incoterm',
        'display_currency',
        'insurance',
        'modes',
      });
      final goods = Map<String, dynamic>.from(j['goods'] as Map);
      expect((goods['total_value'] as Map)['amount'], '2750.00');
      expect(goods['total_weight_kg'], '1600');
      expect(j['modes'], ['air']);
    });
  });

  group('requests', () {
    test('request create / detail / lists', () {
      final r = RfqRequest.fromJson(_obj('request_create'));
      expect(r.buyerId, _myId);
      expect(r.kind, ListingKind.product);
      expect(r.condition, ItemCondition.brandNew);
      expect(r.quantity, '500');
      expect(r.targetPrice?.amount, '4.50');
      expect(r.destination?.city, 'Baghdad');
      expect(r.deadline?.year, 2026);
      expect(r.status, RfqStatus.open);
      expect(r.isLive, isTrue);
      expect(RfqRequest.fromJson(_obj('request_detail')).id, r.id);

      final mine = PageResult.fromJson<RfqRequest>(
          _obj('requests_mine'), RfqRequest.fromJson);
      expect(mine.items, hasLength(2));
      expect(mine.total, 2);
      final any = mine.items.firstWhere((e) => e.title == 'x y z');
      expect(any.condition, isNull);
      expect(any.description, '');
      expect(any.targetPrice, isNull);
      expect(any.destination?.city, isNull);

      final pub = PageResult.fromJson<RfqRequest>(
          _obj('requests_public'), RfqRequest.fromJson);
      expect(pub.items, isEmpty);
    });

    test('draft body only has RequestCreate keys', () {
      final d = RfqDraft(
        kind: ListingKind.product,
        title: 'LED panels',
        quantity: '500',
        unit: 'piece',
        destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
        condition: ItemCondition.used,
        description: 'x',
        targetPrice: const Money(amount: '4.50', currency: 'USD'),
        deadline: DateTime.utc(2026, 12, 1),
      );
      expect(d.toJson().keys.toSet(), {
        'kind',
        'condition',
        'title',
        'description',
        'quantity',
        'unit',
        'target_price',
        'destination',
        'deadline',
      });
    });

    test('offers page and accepted deal', () {
      final page =
          PageResult.fromJson<Offer>(_obj('offers'), Offer.fromJson);
      expect(page.items, hasLength(1));
      final o = page.items.first;
      expect(o.supplierId, 'sup_cn_018');
      expect(o.supplierName, 'Zhongshan Lumina');
      expect(o.unitPrice.amount, '4.20');
      expect(o.moq, 500);
      expect(o.leadTimeDays, 20);
      expect(o.incoterm, Incoterm.fob);
      expect(o.status, OfferStatus.active);
      expect(o.validUntil?.year, 2026);
      expect(o.note, 'ok');

      final deal = Deal.fromJson(_obj('offer_accept'));
      expect(deal.offerId, o.id);
      expect(deal.subtotal.amount, '2100.00');
      expect(deal.commission.amount, '63.00');
      expect(deal.commissionRate, '0.03');
      expect(deal.isEstimate, isFalse);
      expect(deal.supplierNet?.amount, '2037.00');
      expect(deal.unitPrice?.amount, '4.20');
      expect(deal.status, 'pending_payment');
    });
  });

  group('messages', () {
    test('conversation list and create response', () {
      final page = _obj('conversations');
      final c = Conversation.fromJson(
        Map<String, dynamic>.from((page['items'] as List).first as Map),
        myUserId: _myId,
      );
      expect(c.participantId, 'sup_cn_018');
      expect(c.title, 'sup_cn_018');
      expect(c.lastMessage, 'hello there');
      expect(c.unread, 0);
      expect(c.context?.type, 'listing');
      expect(c.context?.id, 'lst_0041');
      expect(c.lastAt.year, 2026);

      final created =
          Conversation.fromJson(_obj('conversation_create'), myUserId: _myId);
      expect(created.id, startsWith('conv_'));
      expect(created.participantId, 'sup_cn_018');
      expect(created.lastMessage, '');
    });

    test('messages page and send response', () {
      final page = _obj('messages');
      final m = ChatMessage.fromJson(
        Map<String, dynamic>.from((page['items'] as List).first as Map),
        myUserId: _myId,
      );
      expect(m.body, 'hello there');
      expect(m.kind, MessageKind.text);
      expect(m.isMine, isTrue);
      expect(m.createdAt.year, 2026);
      final sent = ChatMessage.fromJson(_obj('message_send'), myUserId: _myId);
      expect(sent.isMine, isTrue);
      expect(sent.id, m.id);
      final other = ChatMessage.fromJson(_obj('message_send'));
      expect(other.isMine, isFalse);
    });
  });

  group('tracking', () {
    test('shipment list, create, detail', () {
      final list = _obj('shipments');
      final s = Shipment.fromJson(
          Map<String, dynamic>.from((list['items'] as List).first as Map));
      expect(s.reference, 'MSKU1234565');
      expect(s.referenceType, ReferenceType.container);
      expect(s.carrier, 'Maersk');
      expect(s.status, ShipmentStatus.booked);
      expect(s.origin, 'Xiamen, CN');
      expect(s.destination, 'Dubai, AE');
      expect(s.vesselName, 'Maersk Sentosa');
      expect(s.eta, isNotNull);
      expect(s.progressValue, closeTo(0.05, 0.0001));
      expect(s.events, isNotEmpty);
      expect(s.events.first.status, ShipmentStatus.booked);
      expect(s.events.first.time.year, 2026);
      expect(s.events.first.location, isNotEmpty);
      expect(s.events.first.description, isNotEmpty);
      for (final name in ['shipment_create', 'shipment_detail', 'shipment_detail_delayed']) {
        expect(Shipment.fromJson(_obj(name)).reference, 'MSKU1234565');
      }
    });
  });
}
