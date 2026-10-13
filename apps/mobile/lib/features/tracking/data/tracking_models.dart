/// Feature models for shipment tracking (hand-written JSON).

enum ReferenceType { container, bl, awb, vesselImo }

extension ReferenceTypeX on ReferenceType {
  String get wire {
    switch (this) {
      case ReferenceType.container:
        return 'container';
      case ReferenceType.bl:
        return 'bl';
      case ReferenceType.awb:
        return 'awb';
      case ReferenceType.vesselImo:
        return 'vessel_imo';
    }
  }

  static ReferenceType parse(String? v) {
    switch (v) {
      case 'bl':
        return ReferenceType.bl;
      case 'awb':
        return ReferenceType.awb;
      case 'vessel_imo':
        return ReferenceType.vesselImo;
      default:
        return ReferenceType.container;
    }
  }
}

enum ShipmentStatus {
  booked,
  gateIn,
  loaded,
  departed,
  transshipment,
  arrived,
  discharged,
  customsHold,
  released,
  outForDelivery,
  delivered,
  unknown,
}

extension ShipmentStatusX on ShipmentStatus {
  String get wire {
    switch (this) {
      case ShipmentStatus.gateIn:
        return 'gate_in';
      case ShipmentStatus.customsHold:
        return 'customs_hold';
      case ShipmentStatus.outForDelivery:
        return 'out_for_delivery';
      default:
        return name;
    }
  }

  static ShipmentStatus parse(String? v) {
    for (final s in ShipmentStatus.values) {
      if (s.wire == v) return s;
    }
    return ShipmentStatus.unknown;
  }

  /// Rough journey progress (0..1) used when the server omits `progress`.
  double get defaultProgress {
    switch (this) {
      case ShipmentStatus.booked:
        return 0.05;
      case ShipmentStatus.gateIn:
        return 0.12;
      case ShipmentStatus.loaded:
        return 0.2;
      case ShipmentStatus.departed:
        return 0.35;
      case ShipmentStatus.transshipment:
        return 0.5;
      case ShipmentStatus.arrived:
        return 0.7;
      case ShipmentStatus.discharged:
        return 0.78;
      case ShipmentStatus.customsHold:
        return 0.82;
      case ShipmentStatus.released:
        return 0.88;
      case ShipmentStatus.outForDelivery:
        return 0.95;
      case ShipmentStatus.delivered:
        return 1.0;
      case ShipmentStatus.unknown:
        return 0.0;
    }
  }
}

DateTime? _dt(Object? v) {
  if (v is String) return DateTime.tryParse(v)?.toLocal();
  return null;
}

/// Free-text place from either a plain string (mock) or a contract object:
/// `{name, name_ar, country_code}` (event location) or
/// `{country_code, city}` (shipment origin / destination).
String _place(Object? v, {bool preferArabic = false}) {
  if (v is Map) {
    final ar = v['name_ar']?.toString() ?? '';
    final name = (v['name'] ?? v['city'] ?? '').toString();
    final cc = v['country_code']?.toString() ?? '';
    final label = (preferArabic && ar.isNotEmpty) ? ar : name;
    if (label.isEmpty) return cc;
    return (cc.isEmpty || v['name'] != null) ? label : '$label, $cc';
  }
  return (v ?? '').toString();
}

class TrackingEvent {
  const TrackingEvent({
    required this.status,
    required this.description,
    this.location = '',
    required this.time,
  });

  final ShipmentStatus status;
  final String description;
  final String location;
  final DateTime time;

  factory TrackingEvent.fromJson(Map<String, dynamic> j) => TrackingEvent(
        status: ShipmentStatusX.parse(j['status']?.toString()),
        description: ((j['description_ar'] ?? j['description']) ?? '').toString(),
        location: _place(j['location'], preferArabic: true),
        time: _dt(j['time'] ?? j['timestamp'] ?? j['occurred_at']) ??
            DateTime.fromMillisecondsSinceEpoch(0),
      );

  Map<String, dynamic> toJson() => {
        'status': status.wire,
        'description': description,
        'location': location,
        'time': time.toUtc().toIso8601String(),
      };
}

class Shipment {
  const Shipment({
    required this.id,
    required this.reference,
    required this.referenceType,
    this.carrier,
    this.status = ShipmentStatus.unknown,
    this.origin = '',
    this.destination = '',
    this.vesselName,
    this.eta,
    this.progress,
    this.events = const [],
    this.updatedAt,
  });

  final String id;
  final String reference;
  final ReferenceType referenceType;
  final String? carrier;
  final ShipmentStatus status;
  final String origin;
  final String destination;
  final String? vesselName;
  final DateTime? eta;
  final double? progress;
  final List<TrackingEvent> events;
  final DateTime? updatedAt;

  double get progressValue => (progress ?? status.defaultProgress).clamp(0.0, 1.0).toDouble();

  factory Shipment.fromJson(Map<String, dynamic> j) {
    final rawEvents = j['events'];
    final events = <TrackingEvent>[
      if (rawEvents is List)
        for (final e in rawEvents)
          if (e is Map) TrackingEvent.fromJson(Map<String, dynamic>.from(e)),
    ]..sort((a, b) => b.time.compareTo(a.time));
    final status = j['status'] != null
        ? ShipmentStatusX.parse(j['status'].toString())
        : (events.isNotEmpty ? events.first.status : ShipmentStatus.unknown);
    return Shipment(
      id: j['id'].toString(),
      reference: (j['reference'] ?? '').toString(),
      referenceType: ReferenceTypeX.parse(j['reference_type']?.toString()),
      carrier: j['carrier'] is Map
          ? (j['carrier'] as Map)['name']?.toString()
          : j['carrier']?.toString(),
      status: status,
      origin: _place(j['origin']),
      destination: _place(j['destination']),
      vesselName: (j['vessel_name'] ??
              (j['vessel'] is Map ? (j['vessel'] as Map)['name'] : null))
          ?.toString(),
      eta: _dt(j['eta']),
      progress: (j['progress'] as num?)?.toDouble() ??
          (j['progress_percent'] is num
              ? (j['progress_percent'] as num).toDouble() / 100
              : null),
      events: events,
      updatedAt: _dt(j['updated_at']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'reference': reference,
        'reference_type': referenceType.wire,
        if (carrier != null) 'carrier': carrier,
        'status': status.wire,
        'origin': origin,
        'destination': destination,
        if (vesselName != null) 'vessel_name': vesselName,
        if (eta != null) 'eta': eta!.toUtc().toIso8601String(),
        'progress': progressValue,
        'events': [for (final e in events) e.toJson()],
        if (updatedAt != null) 'updated_at': updatedAt!.toUtc().toIso8601String(),
      };
}
