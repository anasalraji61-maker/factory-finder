import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/tracking/data/reference_validators.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class TrackingRepository {
  Future<List<Shipment>> shipments();
  Future<Shipment> shipment(String id);
  Future<Shipment> add(String reference, ReferenceType type, {String? carrier});
  Future<Shipment> refresh(String id);

  /// Best-effort reference check with did-you-mean and carrier hints.
  Future<ReferenceCheck> validate(ReferenceType type, String reference);
}

class LiveTrackingRepository implements TrackingRepository {
  LiveTrackingRepository(this._api);
  final ApiClient _api;

  Shipment _one(dynamic data) =>
      Shipment.fromJson(Map<String, dynamic>.from(data as Map));

  @override
  Future<List<Shipment>> shipments() async {
    final data = await _api.get('/v1/shipments');
    final raw = data is Map ? (data['items'] ?? const []) : data;
    if (raw is! List) return [];
    return [
      for (final e in raw)
        if (e is Map) Shipment.fromJson(Map<String, dynamic>.from(e)),
    ];
  }

  @override
  Future<Shipment> shipment(String id) async => _one(await _api.get('/v1/shipments/$id'));

  @override
  Future<Shipment> add(String reference, ReferenceType type, {String? carrier}) async =>
      _one(await _api.post('/v1/shipments', body: {
        'reference': normalizeReference(reference),
        'reference_type': type.wire,
        if (carrier != null && carrier.trim().isNotEmpty) 'carrier': carrier.trim(),
      }));

  @override
  Future<ReferenceCheck> validate(ReferenceType type, String reference) async {
    final data = await _api.get(
        '/v1/validate/${type.wire}/${Uri.encodeComponent(normalizeReference(reference))}');
    if (data is! Map) {
      throw ApiException(status: 500, code: 'bad_response', message: 'unexpected response');
    }
    return ReferenceCheck.fromJson(Map<String, dynamic>.from(data));
  }

  @override
  Future<Shipment> refresh(String id) async {
    try {
      return _one(await _api.post('/v1/shipments/$id/refresh'));
    } on ApiException catch (e) {
      // Refreshing right after create is throttled server-side: not an error.
      if (e.code == 'refresh_throttled') return shipment(id);
      rethrow;
    }
  }
}

/// One step of a mock journey: status, Arabic text, location.
class _Step {
  const _Step(this.status, this.text, this.place);
  final ShipmentStatus status;
  final String text;
  final String place;
}

const List<_Step> _seaJourney = [
  _Step(ShipmentStatus.booked, 'تم حجز الشحنة لدى الناقل', 'نينغبو، الصين'),
  _Step(ShipmentStatus.gateIn, 'دخول الحاوية إلى محطة الميناء', 'ميناء نينغبو'),
  _Step(ShipmentStatus.loaded, 'تم تحميل الحاوية على السفينة', 'ميناء نينغبو'),
  _Step(ShipmentStatus.departed, 'غادرت السفينة الميناء', 'ميناء نينغبو'),
  _Step(ShipmentStatus.transshipment, 'تفريغ مؤقت للنقل إلى سفينة أخرى', 'ميناء جبل علي، الإمارات'),
  _Step(ShipmentStatus.arrived, 'وصلت السفينة إلى ميناء الوجهة', 'ميناء أم قصر، العراق'),
  _Step(ShipmentStatus.discharged, 'تم تفريغ الحاوية من السفينة', 'ميناء أم قصر، العراق'),
  _Step(ShipmentStatus.customsHold, 'الحاوية قيد الفحص الجمركي', 'ميناء أم قصر، العراق'),
  _Step(ShipmentStatus.released, 'تم الإفراج الجمركي', 'ميناء أم قصر، العراق'),
  _Step(ShipmentStatus.outForDelivery, 'الشاحنة في الطريق إلى العنوان', 'البصرة → بغداد'),
  _Step(ShipmentStatus.delivered, 'تم التسليم', 'بغداد، العراق'),
];

const List<_Step> _airJourney = [
  _Step(ShipmentStatus.booked, 'تم إصدار بوليصة الشحن الجوي', 'قوانغتشو، الصين'),
  _Step(ShipmentStatus.gateIn, 'استلام الشحنة في مستودع المطار', 'مطار بايون'),
  _Step(ShipmentStatus.loaded, 'تم تحميل الشحنة على الطائرة', 'مطار بايون'),
  _Step(ShipmentStatus.departed, 'أقلعت الطائرة', 'مطار بايون'),
  _Step(ShipmentStatus.arrived, 'هبطت الطائرة في مطار الوجهة', 'مطار بغداد الدولي'),
  _Step(ShipmentStatus.customsHold, 'الشحنة قيد التخليص الجمركي', 'مطار بغداد الدولي'),
  _Step(ShipmentStatus.released, 'تم الإفراج الجمركي', 'مطار بغداد الدولي'),
  _Step(ShipmentStatus.outForDelivery, 'خرجت للتوصيل', 'بغداد'),
  _Step(ShipmentStatus.delivered, 'تم التسليم', 'بغداد'),
];

/// Builds a shipment that has completed the first [done] steps of a journey.
Shipment _buildMockShipment({
  required String id,
  required String reference,
  required ReferenceType type,
  required List<_Step> journey,
  required int done,
  required DateTime now,
  String? carrier,
  String? vessel,
  String origin = 'نينغبو، الصين',
  String destination = 'بغداد، العراق',
  int hoursPerStep = 36,
  int etaDaysFromNow = 14,
}) {
  final n = done.clamp(1, journey.length);
  final events = <TrackingEvent>[
    for (var i = 0; i < n; i++)
      TrackingEvent(
        status: journey[i].status,
        description: journey[i].text,
        location: journey[i].place,
        time: now.subtract(Duration(hours: (n - 1 - i) * hoursPerStep + 3)),
      ),
  ].reversed.toList();
  final status = journey[n - 1].status;
  return Shipment(
    id: id,
    reference: reference,
    referenceType: type,
    carrier: carrier,
    status: status,
    origin: origin,
    destination: destination,
    vesselName: vessel,
    eta: status == ShipmentStatus.delivered
        ? events.first.time
        : now.add(Duration(days: etaDaysFromNow)),
    progress: (n - 1) / (journey.length - 1) * 0.95 + (n == journey.length ? 0.05 : 0),
    events: events,
    updatedAt: now,
  );
}

class MockTrackingRepository implements TrackingRepository {
  MockTrackingRepository({DateTime Function()? clock}) : _clock = clock ?? DateTime.now {
    final now = _clock();
    void put(Shipment s, int done, List<_Step> j) {
      _items[s.id] = s;
      _done[s.id] = done;
      _journeys[s.id] = j;
    }

    Shipment sea(String id, String ref, int done, String carrier, String vessel, int eta) =>
        _buildMockShipment(
          id: id,
          reference: ref,
          type: ReferenceType.container,
          journey: _seaJourney,
          done: done,
          now: now,
          carrier: carrier,
          vessel: vessel,
          etaDaysFromNow: eta,
        );

    put(sea('shp_001', 'MSKU1234565', 2, 'MSC', 'MSC Aurora', 32), 2, _seaJourney);
    put(sea('shp_002', 'TGHU7654320', 4, 'Maersk', 'Maersk Seletar', 24), 4, _seaJourney);
    put(sea('shp_003', 'CMAU9876540', 8, 'CMA CGM', 'CMA CGM Tigris', 4), 8, _seaJourney);
    put(sea('shp_004', 'OOLU5551235', 11, 'OOCL', 'OOCL Hamburg', 0), 11, _seaJourney);
    put(
      _buildMockShipment(
        id: 'shp_005',
        reference: '17612345675',
        type: ReferenceType.awb,
        journey: _airJourney,
        done: 5,
        now: now,
        carrier: 'Emirates SkyCargo',
        origin: 'قوانغتشو، الصين',
        hoursPerStep: 9,
        etaDaysFromNow: 1,
      ),
      5,
      _airJourney,
    );
  }

  final DateTime Function() _clock;
  final Map<String, Shipment> _items = {};
  final Map<String, int> _done = {};
  final Map<String, List<_Step>> _journeys = {};
  int _seq = 5;

  @override
  Future<List<Shipment>> shipments() async {
    final list = _items.values.toList()
      ..sort((a, b) => (b.updatedAt ?? DateTime(1970)).compareTo(a.updatedAt ?? DateTime(1970)));
    return list;
  }

  @override
  Future<Shipment> shipment(String id) async {
    final s = _items[id];
    if (s == null) {
      throw ApiException(status: 404, code: 'not_found', message: 'shipment not found');
    }
    return s;
  }

  @override
  Future<Shipment> add(String reference, ReferenceType type, {String? carrier}) async {
    final key = validateReference(type, reference);
    if (key != null) {
      throw ApiException(status: 422, code: 'invalid_reference', message: key);
    }
    final ref = normalizeReference(reference);
    for (final s in _items.values) {
      if (s.reference == ref) return s;
    }
    final id = 'shp_${(++_seq).toString().padLeft(3, '0')}';
    final journey = type == ReferenceType.awb ? _airJourney : _seaJourney;
    // Deterministic stage from the reference characters.
    final done = 2 + ref.codeUnits.fold<int>(0, (a, b) => a + b) % (journey.length - 3);
    final s = _buildMockShipment(
      id: id,
      reference: ref,
      type: type,
      journey: journey,
      done: done,
      now: _clock(),
      carrier: carrier,
      vessel: type == ReferenceType.awb ? null : 'MV Mock Voyager',
    );
    _items[id] = s;
    _done[id] = done;
    _journeys[id] = journey;
    return s;
  }

  static const Map<String, String> _lookalikes = {
    'O': '0',
    'I': '1',
    'L': '1',
    'B': '8',
    'S': '5',
    'Z': '2',
  };

  static const Map<String, (String, String, String)> _owners = {
    'MSK': ('MAERSK', 'Maersk', 'ميرسك'),
    'MSC': ('MSC', 'MSC', 'إم إس سي'),
    'CMA': ('CMACGM', 'CMA CGM', 'سي إم إيه سي جي إم'),
    'OOL': ('OOCL', 'OOCL', 'أو أو سي إل'),
  };

  @override
  Future<ReferenceCheck> validate(ReferenceType type, String reference) async {
    final ref = normalizeReference(reference);
    final err = validateReference(type, reference);
    final suggestions = <String>[];
    if (err != null && type == ReferenceType.container && ref.length == 11) {
      // Digit positions (4..10) written as look-alike letters, e.g. O for 0.
      for (var i = 4; i < 11 && suggestions.length < 3; i++) {
        final fix = _lookalikes[ref[i]];
        if (fix == null) continue;
        final candidate = ref.replaceRange(i, i + 1, fix);
        if (validateContainer(candidate) == null) suggestions.add(candidate);
      }
    }
    CarrierSuggestion? carrier;
    if (type == ReferenceType.container && ref.length >= 3) {
      final o = _owners[ref.substring(0, 3)];
      if (o != null) {
        carrier = CarrierSuggestion(code: o.$1, name: o.$2, nameAr: o.$3, confidence: 'high');
      }
    }
    return ReferenceCheck(
      valid: err == null,
      normalized: ref,
      reason: err == null ? null : 'format',
      suggestions: suggestions,
      carrierSuggestion: carrier,
    );
  }

  /// Mock refresh advances the journey by one step until delivered.
  @override
  Future<Shipment> refresh(String id) async {
    final s = await shipment(id);
    final journey = _journeys[id]!;
    final done = _done[id]!;
    if (done >= journey.length) return s;
    final next = journey[done];
    final now = _clock();
    final updated = Shipment(
      id: s.id,
      reference: s.reference,
      referenceType: s.referenceType,
      carrier: s.carrier,
      status: next.status,
      origin: s.origin,
      destination: s.destination,
      vesselName: s.vesselName,
      eta: next.status == ShipmentStatus.delivered ? now : s.eta,
      progress: (done) / (journey.length - 1) * 0.95 +
          (done + 1 == journey.length ? 0.05 : 0),
      events: [
        TrackingEvent(
          status: next.status,
          description: next.text,
          location: next.place,
          time: now,
        ),
        ...s.events,
      ],
      updatedAt: now,
    );
    _items[id] = updated;
    _done[id] = done + 1;
    return updated;
  }
}

final trackingRepositoryProvider = Provider<TrackingRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockTrackingRepository() : LiveTrackingRepository(api);
});

final shipmentsProvider = FutureProvider.autoDispose<List<Shipment>>(
  (ref) => ref.watch(trackingRepositoryProvider).shipments(),
);

final shipmentProvider = FutureProvider.autoDispose.family<Shipment, String>(
  (ref, id) => ref.watch(trackingRepositoryProvider).shipment(id),
);
