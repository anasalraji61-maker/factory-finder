import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

ListingPrefill _pf(
  String title,
  double price,
  int qty,
  double kg,
  double m3,
  Incoterm inc,
  String cc,
  String city,
  String hs, {
  String cur = 'USD',
}) =>
    ListingPrefill(
      title: title,
      unitPrice: price,
      currency: cur,
      quantity: qty,
      unitWeightKg: kg,
      unitVolumeM3: m3,
      incoterm: inc,
      origin: Location(countryCode: cc, city: city),
      hsCode: hs,
    );

/// Mock fixture keyed by listing id (kept separate from the discover module).
final Map<String, ListingPrefill> mockPrefills = {
  'lst_001': _pf('Wireless Bluetooth Earbuds TWS', 5.5, 500, 0.06, 0.0002, Incoterm.fob, 'CN', 'Shenzhen', '851830'),
  'lst_002': _pf('Solar LED Street Light 60W', 46, 50, 9, 0.06, Incoterm.exw, 'CN', 'Shenzhen', '940540'),
  'lst_003': _pf('Plain Cotton T-Shirts, Bulk', 2.5, 1000, 0.18, 0.0009, Incoterm.fob, 'CN', 'Guangzhou', '610910'),
  'lst_004': _pf('Polyester Curtain Fabric', 1.8, 2000, 0.35, 0.0012, Incoterm.fob, 'CN', 'Guangzhou', '540754'),
  'lst_005': _pf('Ergonomic Office Chair', 55, 100, 14, 0.22, Incoterm.fob, 'CN', 'Foshan', '940130'),
  'lst_006': _pf('3-Piece Fabric Sofa Set', 395, 20, 95, 1.9, Incoterm.fob, 'CN', 'Foshan', '940161'),
  'lst_007': _pf('Corrugated Shipping Cartons', 0.42, 5000, 0.4, 0.004, Incoterm.exw, 'CN', 'Dongguan', '481910'),
  'lst_008': _pf('PE Stretch Film Pallet Wrap', 14, 300, 2.5, 0.008, Incoterm.fob, 'CN', 'Ningbo', '392190'),
  'lst_009': _pf('Smart Watch Fitness Tracker', 12, 300, 0.12, 0.0004, Incoterm.fob, 'CN', 'Yiwu', '910212'),
  'lst_010': _pf('HDPE Resin Granules', 1115, 20, 1000, 1.6, Incoterm.cfr, 'CN', 'Ningbo', '390120'),
  'lst_011': _pf('PVC Resin SG-5', 820, 25, 1000, 1.5, Incoterm.cif, 'CN', 'Ningbo', '390410'),
  'lst_012': _pf('Hot-Rolled Steel Coil', 555, 50, 1000, 0.45, Incoterm.fob, 'CN', 'Tangshan', '720836'),
  'lst_013': _pf('Rebar Steel Bars 12mm', 510, 100, 1000, 0.4, Incoterm.fob, 'CN', 'Tangshan', '721420'),
  'lst_014': _pf('Aluminum Ingot A7', 2435, 20, 1000, 0.37, Incoterm.fob, 'CN', 'Tangshan', '760110'),
  'lst_015': _pf('Combed Cotton Yarn', 3.75, 500, 1, 0.0025, Incoterm.fob, 'TR', 'Bursa', '520512'),
  'lst_016': _pf('Caustic Soda Flakes 99%', 415, 25, 1000, 0.8, Incoterm.fob, 'CN', 'Hangzhou', '281511'),
  'lst_017': _pf('PET Bottle Blowing Line', 32000, 1, 4200, 14, Incoterm.fob, 'CN', 'Foshan', '847730'),
  'lst_018': _pf('Used Injection Molding Machine 250T', 16000, 1, 9500, 18, Incoterm.fob, 'CN', 'Foshan', '847710'),
  'lst_019': _pf('Pasta Production Line', 125000, 1, 12000, 38, Incoterm.fca, 'IT', 'Parma', '843859', cur: 'EUR'),
  'lst_020': _pf('Used Filling & Capping Line', 36500, 1, 6800, 24, Incoterm.exw, 'DE', 'Munich', '842240', cur: 'EUR'),
  'lst_021': _pf('Used Mazak CNC Lathe', 23750, 1, 5200, 11, Incoterm.fca, 'US', 'Chicago', '845810'),
  'lst_022': _pf('Refurbished Bakery Line', 52000, 1, 7800, 26, Incoterm.fca, 'IT', 'Parma', '843810', cur: 'EUR'),
  'lst_023': _pf('Plastic Bag Extrusion Machine', 11650, 1, 2100, 6, Incoterm.fob, 'CN', 'Foshan', '847720'),
  'lst_024': _pf('Used Metal Stamping Press 160T', 13250, 1, 8500, 14, Incoterm.exw, 'US', 'Chicago', '846299'),
};

class LogisticsRepository {
  LogisticsRepository(this._api, {DateTime Function()? clock}) : _clock = clock ?? DateTime.now;

  final ApiClient _api;

  /// Clock used by the mock generator to judge freight-override validity.
  final DateTime Function() _clock;

  Future<LandedCostQuote> calculate(QuoteRequest r, {String lang = 'ar'}) async {
    if (_api.isMock) {
      await mockDelay(700);
      return MockQuoteGenerator.generate(r, lang: lang, now: _clock());
    }
    final json = await _api.post('/v1/quotes/landed-cost', body: r.toJson());
    return LandedCostQuote.fromJson(Map<String, dynamic>.from(json as Map));
  }

  Future<ListingPrefill?> prefill(String listingId) async {
    if (_api.isMock) {
      await mockDelay(150);
      return mockPrefills[listingId];
    }
    final json = await _api.get('/v1/listings/$listingId');
    final l = Listing.fromJson(Map<String, dynamic>.from(json as Map));
    return ListingPrefill(
      title: l.title,
      unitPrice: (l.price.min.value + l.price.max.value) / 2,
      currency: l.price.min.currency,
      quantity: l.moq ?? 1,
      unitWeightKg: l.unitWeightKg ?? 1,
      unitVolumeM3: l.unitVolumeM3 ?? 0.01,
      incoterm: l.incoterm ?? Incoterm.fob,
      origin: l.origin ?? l.supplier.location,
      hsCode: l.hsCode,
    );
  }
}

final logisticsRepositoryProvider = Provider<LogisticsRepository>(
  (ref) => LogisticsRepository(ref.watch(apiClientProvider)),
);

/// The most recent quote, shown on the results screen.
final lastQuoteProvider = StateProvider<LandedCostQuote?>((ref) => null);

/// One-shot hand-over to the calculator (awarded freight quote -> landed cost).
/// The calculator reads and clears it on open.
final calculatorSeedProvider = StateProvider<CalculatorSeed?>((ref) => null);

final prefillProvider =
    FutureProvider.autoDispose.family<ListingPrefill?, String>(
  (ref, id) => ref.watch(logisticsRepositoryProvider).prefill(id),
);
