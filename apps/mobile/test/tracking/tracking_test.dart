import 'package:factory_finder/features/tracking/data/reference_validators.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('container ISO 6346', () {
    test('valid numbers', () {
      expect(validateContainer('CSQU3054383'), isNull);
      expect(validateContainer('msku 123456-5'), isNull);
      expect(containerCheckDigit('CSQU305438'), 3);
    });
    test('bad check digit and format', () {
      expect(validateContainer('CSQU3054384'), 'tracking.err.container_check');
      expect(validateContainer('CSQX3054383'), 'tracking.err.container_format');
      expect(validateContainer('ABC'), 'tracking.err.container_format');
    });
  });

  group('AWB mod 7', () {
    test('valid', () {
      expect(validateAwb('176-12345675'), isNull);
      expect(validateAwb('17612345675'), isNull);
    });
    test('invalid', () {
      expect(validateAwb('176-12345676'), 'tracking.err.awb_check');
      expect(validateAwb('1761234'), 'tracking.err.awb_format');
    });
  });

  group('IMO and B/L', () {
    test('IMO', () {
      expect(validateImo('9074729'), isNull);
      expect(validateImo('IMO 9074729'), isNull);
      expect(validateImo('9074728'), 'tracking.err.imo_check');
      expect(validateImo('12'), 'tracking.err.imo_format');
    });
    test('B/L and dispatcher', () {
      expect(validateBl('MEDUXX123456'), isNull);
      expect(validateBl('ab'), 'tracking.err.bl_format');
      expect(validateReference(ReferenceType.container, ''), 'tracking.err.empty');
      expect(validateReference(ReferenceType.awb, '176-12345675'), isNull);
    });
  });

  test('shipment JSON round trip', () async {
    final repo = MockTrackingRepository(clock: () => DateTime(2026, 10, 13, 12));
    final s = (await repo.shipments()).first;
    final back = Shipment.fromJson(s.toJson());
    expect(back.id, s.id);
    expect(back.status, s.status);
    expect(back.events.length, s.events.length);
    expect(back.referenceType, s.referenceType);
    expect(back.progressValue, closeTo(s.progressValue, 1e-9));
  });

  test('mock fixtures: >= 5 shipments in different stages', () async {
    final repo = MockTrackingRepository(clock: () => DateTime(2026, 10, 13, 12));
    final list = await repo.shipments();
    expect(list.length, greaterThanOrEqualTo(5));
    expect(list.map((s) => s.status).toSet().length, greaterThanOrEqualTo(5));
    for (final s in list) {
      expect(s.events, isNotEmpty);
      expect(s.progressValue, inInclusiveRange(0.0, 1.0));
      expect(s.events.first.status, s.status);
    }
  });

  test('add validates, dedupes and refresh advances', () async {
    final repo = MockTrackingRepository(clock: () => DateTime(2026, 10, 13, 12));
    expect(() => repo.add('CSQU3054384', ReferenceType.container), throwsA(anything));
    final s = await repo.add('csqu 3054383', ReferenceType.container, carrier: 'MSC');
    expect(s.reference, 'CSQU3054383');
    final again = await repo.add('CSQU3054383', ReferenceType.container);
    expect(again.id, s.id);
    final r = await repo.refresh(s.id);
    expect(r.events.length, s.events.length + 1);
    expect(r.progressValue, greaterThanOrEqualTo(s.progressValue));
    final done = await repo.refresh('shp_004');
    expect(done.events.length, (await repo.shipment('shp_004')).events.length);
  });
}
