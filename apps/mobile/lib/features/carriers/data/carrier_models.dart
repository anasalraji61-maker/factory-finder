/// Mode groups shown as filter chips. `null` group means all.
const List<String> kCarrierModeGroups = ['sea', 'air', 'rail', 'road'];

/// Maps a contract TransportMode (sea_lcl, sea_fcl_20, air, rail, road) to a group.
String modeGroup(String mode) {
  if (mode.startsWith('sea')) return 'sea';
  return mode;
}

/// Directory entry from GET /v1/carriers.
class Carrier {
  const Carrier({
    required this.id,
    required this.name,
    this.kind = 'carrier',
    this.modes = const [],
    this.originRegions = const [],
    this.destinationRegions = const [],
    this.rating = 0,
  });

  final String id;
  final String name;
  final String kind; // carrier | forwarder | airline
  final List<String> modes;
  final List<String> originRegions;
  final List<String> destinationRegions;
  final double rating;

  static List<String> _strings(dynamic v) =>
      v is List ? [for (final e in v) e.toString()] : <String>[];

  factory Carrier.fromJson(Map<String, dynamic> json) {
    final r = json['rating'];
    return Carrier(
      id: (json['id'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
      kind: (json['kind'] ?? 'carrier').toString(),
      modes: _strings(json['modes']),
      originRegions: _strings(json['origin_regions']),
      destinationRegions: _strings(json['destination_regions']),
      rating: r is num ? r.toDouble() : (double.tryParse('${r ?? ''}') ?? 0),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'kind': kind,
        'modes': modes,
        'origin_regions': originRegions,
        'destination_regions': destinationRegions,
        'rating': rating,
      };

  bool matchesGroup(String? group) =>
      group == null || modes.any((m) => modeGroup(m) == group);
}

List<Carrier> filterByModeGroup(List<Carrier> all, String? group) =>
    [for (final c in all) if (c.matchesGroup(group)) c];

/// True for a 2-letter uppercase ISO country code.
bool isCountryCode(String s) => RegExp(r'^[A-Z]{2}$').hasMatch(s);
