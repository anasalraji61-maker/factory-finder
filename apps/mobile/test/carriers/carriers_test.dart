import 'package:factory_finder/features/carriers/data/carrier_models.dart';
import 'package:factory_finder/features/carriers/data/carriers_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Carrier JSON round-trip', () {
    final json = {
      'id': 'car_msc',
      'name': 'MSC',
      'kind': 'carrier',
      'modes': ['sea_fcl_20', 'sea_lcl'],
      'origin_regions': ['CN'],
      'destination_regions': ['IQ'],
      'rating': 4.5,
    };
    final c = Carrier.fromJson(json);
    expect(c.rating, 4.5);
    expect(c.toJson(), json);
  });

  test('mode group filter', () {
    expect(modeGroup('sea_fcl_40hc'), 'sea');
    expect(modeGroup('air'), 'air');
    final all = kMockCarriers;
    expect(all.length, 12);
    final sea = filterByModeGroup(all, 'sea');
    expect(sea.isNotEmpty, true);
    expect(sea.every((c) => c.modes.any((m) => m.startsWith('sea'))), true);
    expect(filterByModeGroup(all, null).length, all.length);
    for (final g in kCarrierModeGroups) {
      expect(filterByModeGroup(all, g).isNotEmpty, true);
    }
  });

  test('mock repo lane filter', () async {
    final repo = MockCarriersRepository();
    final r = await repo.carriers(originCountry: 'CN', destinationCountry: 'IQ');
    expect(r.every((c) => c.originRegions.contains('CN')), true);
    final air = await repo.carriers(mode: 'air');
    expect(air.every((c) => c.modes.contains('air')), true);
  });
}
