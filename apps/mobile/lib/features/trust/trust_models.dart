/// Trust v2 extras: score history and buyer concern reports.
/// Pure Dart (no Flutter imports) so parsing/validation is unit-testable.

class TrustHistoryPoint {
  const TrustHistoryPoint({
    required this.at,
    required this.score,
    this.band,
    this.confidence,
    this.source,
  });

  final DateTime at;
  final int score;
  final String? band;
  final int? confidence;
  final String? source;
}

/// Oldest-first, skips malformed points, sorts defensively by time.
List<TrustHistoryPoint> parseTrustHistory(Object? json) {
  final raw = json is Map ? json['points'] : json;
  if (raw is! List) return const <TrustHistoryPoint>[];
  final out = <TrustHistoryPoint>[];
  for (final e in raw) {
    if (e is! Map) continue;
    final at = DateTime.tryParse(e['at']?.toString() ?? '');
    final score = e['score'];
    if (at == null || score is! num) continue;
    final conf = e['confidence'];
    out.add(TrustHistoryPoint(
      at: at,
      score: score.round().clamp(0, 100).toInt(),
      band: e['band']?.toString(),
      confidence: conf is num ? conf.round().clamp(0, 100).toInt() : null,
      source: e['source']?.toString(),
    ));
  }
  out.sort((a, b) => a.at.compareTo(b.at));
  return out;
}

const int kReportMaxLength = 1000;

/// Contract enum SupplierReportIn.type.
const List<String> kReportTypes = [
  'fraud',
  'counterfeit',
  'non_delivery',
  'quality',
  'misrepresentation',
  'unsafe_product',
  'other',
];

/// Returns an i18n key for the first problem, or null when valid.
String? validateReport(String? type, String text) {
  if (type == null || !kReportTypes.contains(type)) return 'trust.report.err_type';
  final t = text.trim();
  if (t.isEmpty) return 'trust.report.err_text';
  if (t.length > kReportMaxLength) return 'trust.report.err_long';
  return null;
}

class ReportResult {
  const ReportResult({required this.id, required this.status});

  final String id;
  final String status;

  factory ReportResult.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    return ReportResult(
      id: m['id']?.toString() ?? '',
      status: m['status']?.toString() ?? 'pending_review',
    );
  }
}

/// Human label for flags the server may add later; unknown flags fall back to
/// the raw string.
const List<String> kKnownTrustFlags = [
  'sanctions_hit',
  'blocked_flag',
  'price_anomaly',
  'certification_expired',
  'certification_expiring',
];
