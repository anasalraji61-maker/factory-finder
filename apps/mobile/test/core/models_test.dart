import 'dart:convert';

import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _roundTrip(Map<String, dynamic> json) =>
    jsonDecode(jsonEncode(json)) as Map<String, dynamic>;

void main() {
  group('enum parsers', () {
    test('every enum value round-trips through its json', () {
      for (final v in ListingKind.values) {
        expect(listingKindFromJson(v.json), v);
      }
      for (final v in ItemCondition.values) {
        expect(itemConditionFromJson(v.json), v);
      }
      for (final v in TransportMode.values) {
        expect(transportModeFromJson(v.json), v);
      }
      for (final v in Incoterm.values) {
        expect(incotermFromJson(v.json), v);
      }
      for (final v in TrustBand.values) {
        expect(trustBandFromJson(v.json), v);
      }
    });

    test('json values match the common schema', () {
      expect(ListingKind.rawMaterial.json, 'raw_material');
      expect(ListingKind.productionLine.json, 'production_line');
      expect(ItemCondition.brandNew.json, 'new');
      expect(TransportMode.seaFcl40hc.json, 'sea_fcl_40hc');
      expect(Incoterm.cif.json, 'CIF');
    });

    test('unknown values fall back safely', () {
      expect(trustBandFromJson('nope'), TrustBand.unknown);
      expect(listingKindFromJson('nope'), ListingKind.product);
    });
  });

  group('Money formatting', () {
    test('Money.format', () {
      expect(const Money(amount: '1234.5', currency: 'USD').format(), r'$1,234.50');
      expect(const Money(amount: '9.99', currency: 'EUR').format(), '€9.99');
      expect(const Money(amount: '1500', currency: 'IQD').format(), 'IQD 1,500');
      expect(const Money(amount: '12', currency: 'TRY').format(), 'TRY 12.00');
      expect(const Money(amount: '2.5', currency: 'USD').value, 2.5);
    });

    test('MoneyRange.format', () {
      const r = MoneyRange(
        min: Money(amount: '1.2', currency: 'USD'),
        max: Money(amount: '1.8', currency: 'USD'),
      );
      expect(r.format(), r'$1.20 – $1.80');
      const same = MoneyRange(
        min: Money(amount: '5', currency: 'USD'),
        max: Money(amount: '5', currency: 'USD'),
      );
      expect(same.format(), r'$5.00');
    });
  });

  group('JSON round trips', () {
    test('Listing (all mock listings)', () {
      for (final l in mockListings) {
        final json = _roundTrip(l.toJson());
        expect(Listing.fromJson(json).toJson(), json);
      }
    });

    test('Listing parses a schema-shaped document', () {
      final l = Listing.fromJson({
        'id': 'x1',
        'source': 'mock',
        'kind': 'raw_material',
        'condition': 'used',
        'title': 'Steel',
        'title_ar': 'حديد',
        'price': {
          'min': {'amount': '1.50', 'currency': 'USD'},
          'max': {'amount': '2.00', 'currency': 'USD'},
        },
        'moq': 10,
        'incoterm': 'FOB',
        'lead_time_days': {'min': 5, 'max': 9},
        'supplier': {
          'id': 'sup_cn_001',
          'name': 'S',
          'location': {'country_code': 'CN', 'city': 'Shenzhen'},
          'trust_score': 80,
          'trust_band': 'green',
        },
      });
      expect(l.kind, ListingKind.rawMaterial);
      expect(l.condition, ItemCondition.used);
      expect(l.displayTitle('ar'), 'حديد');
      expect(l.displayTitle('en'), 'Steel');
      expect(l.unit, 'piece');
      expect(l.supplier.trustBand, TrustBand.green);
      expect(l.leadTimeDays!.max, 9);
    });

    test('LandedCostQuote', () {
      final quote = MockQuoteGenerator.generate(
        const QuoteRequest(
          goodsValue: 10000,
          weightKg: 2000,
          volumeM3: 8,
          origin: Location(countryCode: 'CN', city: 'Guangzhou'),
          destination: Location(countryCode: 'IQ', city: 'Baghdad'),
        ),
        lang: 'en',
        now: DateTime.utc(2026, 10, 1),
      );
      final json = _roundTrip(quote.toJson());
      expect(LandedCostQuote.fromJson(json).toJson(), json);
    });

    test('TrustScore + PageResult', () {
      final trust = mockTrustFor(mockSuppliers['sup_cn_004']!);
      final json = _roundTrip(trust.toJson());
      expect(TrustScore.fromJson(json).toJson(), json);
      // Factor impacts add up to score - 50 (baseline).
      expect(trust.factors.fold<int>(0, (a, f) => a + f.impact), trust.score - 50);

      final page = PageResult.fromJson<Listing>(
        {
          'items': [mockListings.first.toJson()],
          'total': 1,
          'page': 1,
          'page_size': 20,
        },
        Listing.fromJson,
      );
      expect(page.items.single.id, mockListings.first.id);
      expect(page.total, 1);
    });
  });

  group('AppStrings', () {
    test('core strings and fallbacks', () {
      expect(AppStrings.lookup('ar', 'nav.discover'), 'استكشف');
      expect(AppStrings.lookup('en', 'nav.discover'), 'Discover');
      expect(AppStrings.lookup('fr', 'nav.discover'), 'Discover');
      expect(AppStrings.lookup('ar', 'totally.missing'), 'totally.missing');
    });

    test('register merges and substitutes placeholders', () {
      AppStrings.register({
        'en': {'test.only_en': 'Hello {name}'},
      });
      expect(AppStrings.lookup('ar', 'test.only_en', {'name': 'Ali'}), 'Hello Ali');
    });
  });
}
