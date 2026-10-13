import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/carriers/data/carrier_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class CarriersRepository {
  Future<List<Carrier>> carriers({
    String? originCountry,
    String? destinationCountry,
    String? mode,
  });
}

class LiveCarriersRepository implements CarriersRepository {
  LiveCarriersRepository(this._api);
  final ApiClient _api;

  @override
  Future<List<Carrier>> carriers({
    String? originCountry,
    String? destinationCountry,
    String? mode,
  }) async {
    final data = await _api.get('/v1/carriers', query: {
      if (originCountry != null) 'origin_country': originCountry,
      if (destinationCountry != null) 'destination_country': destinationCountry,
      if (mode != null) 'mode': mode,
    });
    final raw = data is Map ? (data['items'] ?? const []) : data;
    if (raw is! List) return [];
    return [
      for (final e in raw)
        if (e is Map) Carrier.fromJson(Map<String, dynamic>.from(e)),
    ];
  }
}

const List<Carrier> kMockCarriers = [
  Carrier(id: 'car_msc', name: 'MSC', kind: 'carrier', modes: ['sea_fcl_20', 'sea_fcl_40', 'sea_fcl_40hc', 'sea_lcl'], originRegions: ['CN', 'TR', 'DE'], destinationRegions: ['IQ', 'AE', 'SA'], rating: 4.5),
  Carrier(id: 'car_maersk', name: 'Maersk', kind: 'carrier', modes: ['sea_fcl_20', 'sea_fcl_40', 'sea_fcl_40hc'], originRegions: ['CN', 'US', 'DE'], destinationRegions: ['IQ', 'AE', 'KW'], rating: 4.7),
  Carrier(id: 'car_cosco', name: 'COSCO Shipping', kind: 'carrier', modes: ['sea_fcl_20', 'sea_fcl_40', 'sea_fcl_40hc'], originRegions: ['CN'], destinationRegions: ['IQ', 'AE', 'TR'], rating: 4.3),
  Carrier(id: 'car_cma', name: 'CMA CGM', kind: 'carrier', modes: ['sea_fcl_20', 'sea_fcl_40', 'sea_lcl'], originRegions: ['CN', 'IN', 'IT'], destinationRegions: ['IQ', 'JO', 'EG'], rating: 4.4),
  Carrier(id: 'car_hapag', name: 'Hapag-Lloyd', kind: 'carrier', modes: ['sea_fcl_20', 'sea_fcl_40'], originRegions: ['DE', 'US', 'CN'], destinationRegions: ['IQ', 'SA'], rating: 4.5),
  Carrier(id: 'fwd_dhl', name: 'DHL Global Forwarding', kind: 'forwarder', modes: ['air', 'sea_lcl', 'road'], originRegions: ['CN', 'US', 'DE'], destinationRegions: ['IQ', 'AE', 'TR'], rating: 4.2),
  Carrier(id: 'fwd_kn', name: 'Kuehne+Nagel', kind: 'forwarder', modes: ['air', 'sea_lcl', 'sea_fcl_40', 'road'], originRegions: ['DE', 'CN', 'US'], destinationRegions: ['IQ', 'KW'], rating: 4.4),
  Carrier(id: 'fwd_gulf', name: 'Gulf Agency Co.', kind: 'forwarder', modes: ['sea_lcl', 'road'], originRegions: ['AE', 'TR'], destinationRegions: ['IQ'], rating: 3.9),
  Carrier(id: 'air_qatar', name: 'Qatar Airways Cargo', kind: 'airline', modes: ['air'], originRegions: ['CN', 'US', 'DE', 'IN'], destinationRegions: ['IQ', 'SA', 'AE'], rating: 4.6),
  Carrier(id: 'air_turkish', name: 'Turkish Cargo', kind: 'airline', modes: ['air'], originRegions: ['CN', 'TR', 'IT'], destinationRegions: ['IQ', 'IR', 'JO'], rating: 4.5),
  Carrier(id: 'rail_silk', name: 'Silk Road Rail Express', kind: 'forwarder', modes: ['rail'], originRegions: ['CN'], destinationRegions: ['TR', 'DE', 'IR'], rating: 3.8),
  Carrier(id: 'road_kapikule', name: 'Anatolia Road Freight', kind: 'carrier', modes: ['road'], originRegions: ['TR', 'IR'], destinationRegions: ['IQ', 'SY', 'JO'], rating: 3.7),
];

class MockCarriersRepository implements CarriersRepository {
  @override
  Future<List<Carrier>> carriers({
    String? originCountry,
    String? destinationCountry,
    String? mode,
  }) async {
    return [
      for (final c in kMockCarriers)
        if ((originCountry == null || c.originRegions.contains(originCountry)) &&
            (destinationCountry == null ||
                c.destinationRegions.contains(destinationCountry)) &&
            (mode == null || c.modes.contains(mode)))
          c,
    ];
  }
}

final carriersRepositoryProvider = Provider<CarriersRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockCarriersRepository() : LiveCarriersRepository(api);
});

/// Selected mode group (null = all).
final carrierModeGroupProvider = StateProvider<String?>((ref) => null);

final carriersProvider = FutureProvider.autoDispose<List<Carrier>>(
  (ref) => ref.watch(carriersRepositoryProvider).carriers(),
);
