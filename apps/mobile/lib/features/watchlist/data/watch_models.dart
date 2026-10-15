/// Models for the watchlist / price-alert feature (hand-written, tolerant JSON).
import 'package:factory_finder/core/models/models.dart';

DateTime? _dt(Object? v) {
  if (v is String) return DateTime.tryParse(v)?.toLocal();
  return null;
}

Money? _money(Object? v) {
  if (v is Map) return Money.fromJson(Map<String, dynamic>.from(v));
  return null;
}

String? _str(Object? v) {
  if (v == null) return null;
  final s = v.toString();
  return s.isEmpty ? null : s;
}

int _intOr(Object? v, int fallback) {
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? fallback;
  return fallback;
}

/// One watched listing (or saved search) from `GET /v1/watchlist`.
class WatchItem {
  const WatchItem({
    required this.id,
    this.type = 'listing',
    this.listingId,
    this.search,
    this.targetPrice,
    this.dropThresholdPct = '5',
    this.active = true,
    this.title,
    this.titleAr,
    this.baselinePrice,
    this.currentPrice,
    this.available,
    this.resultCount,
    this.lastCheckedAt,
    this.createdAt,
  });

  final String id;
  final String type; // 'listing' | 'search'
  final String? listingId;

  /// Saved-search query (`SearchQuery` in notifications.yaml) for type 'search'.
  final Map<String, dynamic>? search;
  final Money? targetPrice;
  final String dropThresholdPct;
  final bool active;
  final String? title;
  final String? titleAr;
  final Money? baselinePrice;
  final Money? currentPrice;
  final bool? available;
  final int? resultCount;
  final DateTime? lastCheckedAt;
  final DateTime? createdAt;

  bool get isListing => type == 'listing' && listingId != null;

  String displayTitle(String lang) {
    final ar = titleAr;
    if (lang == 'ar' && ar != null && ar.isNotEmpty) return ar;
    final t = title;
    if (t != null && t.isNotEmpty) return t;
    return listingId ?? id;
  }

  /// True when the current price is at or below the target price.
  bool get reachedTarget {
    final t = targetPrice;
    final c = currentPrice;
    if (t == null || c == null) return false;
    return c.currency == t.currency && c.value <= t.value;
  }

  factory WatchItem.fromJson(Map<String, dynamic> j) => WatchItem(
        id: (j['id'] ?? '').toString(),
        type: (j['type'] ?? 'listing').toString(),
        listingId: _str(j['listing_id']),
        search: j['search'] is Map ? Map<String, dynamic>.from(j['search'] as Map) : null,
        targetPrice: _money(j['target_price']),
        dropThresholdPct: (j['drop_threshold_pct'] ?? '5').toString(),
        active: j['active'] is bool ? j['active'] as bool : true,
        title: _str(j['title']),
        titleAr: _str(j['title_ar']),
        baselinePrice: _money(j['baseline_price']),
        currentPrice: _money(j['current_price']),
        available: j['available'] is bool ? j['available'] as bool : null,
        resultCount: j['result_count'] is num ? (j['result_count'] as num).toInt() : null,
        lastCheckedAt: _dt(j['last_checked_at']),
        createdAt: _dt(j['created_at']),
      );
}

/// `GET /v1/watchlist` envelope: `{items, total}`.
List<WatchItem> parseWatchList(dynamic data) {
  final raw = data is Map ? (data['items'] ?? const []) : data;
  if (raw is! List) return const [];
  return [
    for (final e in raw)
      if (e is Map) WatchItem.fromJson(Map<String, dynamic>.from(e)),
  ];
}

const String kRuleShipmentStatus = 'shipment_status';
const String kRuleShipmentDelayed = 'shipment_delayed';

/// `payload.shipment` of shipment alerts (all fields optional / tolerant).
class AlertShipment {
  const AlertShipment({
    required this.shipmentId,
    this.kind,
    this.reference,
    this.referenceType,
    this.label,
    this.status,
    this.previousStatus,
    this.eta,
    this.delayed = false,
    this.delayHours,
  });

  final String shipmentId;
  final String? kind;
  final String? reference;
  final String? referenceType;
  final String? label;
  final String? status;
  final String? previousStatus;
  final String? eta;
  final bool delayed;
  final int? delayHours;

  /// Null when there is no usable shipment id.
  static AlertShipment? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final id = raw['shipment_id']?.toString() ?? '';
    if (id.isEmpty) return null;
    String? s(Object? v) {
      final t = v?.toString() ?? '';
      return t.isEmpty ? null : t;
    }

    final dh = raw['delay_hours'];
    return AlertShipment(
      shipmentId: id,
      kind: s(raw['kind']),
      reference: s(raw['reference']),
      referenceType: s(raw['reference_type']),
      label: s(raw['label']),
      status: s(raw['status']),
      previousStatus: s(raw['previous_status']),
      eta: s(raw['eta']),
      delayed: raw['delayed'] == true,
      delayHours: dh is num ? dh.toInt() : int.tryParse(dh?.toString() ?? ''),
    );
  }
}

final RegExp _routeIdPattern = RegExp(r'^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$');

/// True for an opaque id that is safe as ONE path segment (no slashes, query,
/// fragment, whitespace, `..`).
bool isSafeRouteId(String? id) =>
    id != null && _routeIdPattern.hasMatch(id) && !id.contains('..');

/// `/listing/<id>` for a safe id, else null.
String? safeListingRoute(String? id) =>
    isSafeRouteId(id) ? '/listing/${Uri.encodeComponent(id!)}' : null;

/// One inbox alert from `GET /v1/alerts`.
class PriceAlert {
  const PriceAlert({
    required this.id,
    required this.watchId,
    this.rule = 'price_drop',
    this.title = '',
    this.titleAr = '',
    this.body = '',
    this.bodyAr = '',
    this.payload = const {},
    this.read = false,
    this.createdAt,
    this.readAt,
  });

  final String id;
  final String watchId;
  final String rule;
  final String title;
  final String titleAr;
  final String body;
  final String bodyAr;
  final Map<String, dynamic> payload;
  final bool read;
  final DateTime? createdAt;
  final DateTime? readAt;

  String displayTitle(String lang) => (lang == 'ar' && titleAr.isNotEmpty) ? titleAr : title;
  String displayBody(String lang) => (lang == 'ar' && bodyAr.isNotEmpty) ? bodyAr : body;

  /// First listing id in `payload.listing_ids`, if any.
  String? get listingId {
    final ids = payload['listing_ids'];
    if (ids is List && ids.isNotEmpty) {
      final first = ids.first;
      if (first is String || first is num) return first.toString();
    }
    return null;
  }

  /// Internal listing route for this alert, or null when the id is missing or
  /// unsafe (server-supplied data must never shape an arbitrary path).
  String? get listingRoute => safeListingRoute(listingId);

  bool get isShipment => rule == kRuleShipmentStatus || rule == kRuleShipmentDelayed;

  /// Parsed `payload.shipment`, or null (not a shipment alert / malformed).
  AlertShipment? get shipment => AlertShipment.tryParse(payload['shipment']);

  /// Tracking detail route for shipment alerts, else null.
  String? get trackingRoute {
    final sh = shipment;
    if (sh == null || !isSafeRouteId(sh.shipmentId)) return null;
    return '/logistics/tracking/${Uri.encodeComponent(sh.shipmentId)}';
  }

  PriceAlert copyWith({bool? read, DateTime? readAt}) => PriceAlert(
        id: id,
        watchId: watchId,
        rule: rule,
        title: title,
        titleAr: titleAr,
        body: body,
        bodyAr: bodyAr,
        payload: payload,
        read: read ?? this.read,
        createdAt: createdAt,
        readAt: readAt ?? this.readAt,
      );

  factory PriceAlert.fromJson(Map<String, dynamic> j) => PriceAlert(
        id: (j['id'] ?? '').toString(),
        watchId: (j['watch_id'] ?? '').toString(),
        rule: (j['rule'] ?? 'price_drop').toString(),
        title: (j['title'] ?? '').toString(),
        titleAr: (j['title_ar'] ?? '').toString(),
        body: (j['body'] ?? '').toString(),
        bodyAr: (j['body_ar'] ?? '').toString(),
        payload: j['payload'] is Map ? Map<String, dynamic>.from(j['payload'] as Map) : const {},
        read: j['read'] == true,
        createdAt: _dt(j['created_at']),
        readAt: _dt(j['read_at']),
      );
}

/// `GET /v1/alerts` envelope.
class AlertPage {
  const AlertPage({
    this.items = const [],
    this.total = 0,
    this.page = 1,
    this.pageSize = 20,
    this.unreadTotal = 0,
  });

  final List<PriceAlert> items;
  final int total;
  final int page;
  final int pageSize;
  final int unreadTotal;

  factory AlertPage.fromJson(Map<String, dynamic> j) {
    final raw = j['items'];
    final items = <PriceAlert>[
      if (raw is List)
        for (final e in raw)
          if (e is Map) PriceAlert.fromJson(Map<String, dynamic>.from(e)),
    ];
    return AlertPage(
      items: items,
      total: _intOr(j['total'], items.length),
      page: _intOr(j['page'], 1),
      pageSize: _intOr(j['page_size'], items.length),
      unreadTotal: _intOr(j['unread_total'], items.where((a) => !a.read).length),
    );
  }
}
