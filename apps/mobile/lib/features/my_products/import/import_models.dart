/// One per-item result of `POST /v1/my/listings/import` (`ListingImportResult`).
class ImportItemResult {
  const ImportItemResult({
    required this.index,
    required this.action,
    this.externalRef,
    this.id,
    this.status,
    this.moderation,
    this.reason,
    this.message,
  });

  /// Position inside the request batch (0-based).
  final int index;

  /// `created` | `updated` | `rejected`.
  final String action;
  final String? externalRef;
  final String? id;
  final String? status;
  final String? moderation;

  /// Only when rejected: validation_error, invalid_item, duplicate_in_batch,
  /// listing_cap_reached, conflict.
  final String? reason;
  final String? message;

  bool get isRejected => action == 'rejected';

  factory ImportItemResult.fromJson(Map<String, dynamic> j) {
    String? s(Object? v) => v is String && v.isNotEmpty ? v : null;
    final idx = j['index'];
    return ImportItemResult(
      index: idx is num ? idx.toInt() : 0,
      action: s(j['action']) ?? 'rejected',
      externalRef: s(j['external_ref']),
      id: s(j['id']),
      status: s(j['status']),
      moderation: s(j['moderation']),
      reason: s(j['reason']),
      message: s(j['message']),
    );
  }
}

/// `ListingImportResponse`.
class ImportResponse {
  const ImportResponse({
    required this.dryRun,
    required this.created,
    required this.updated,
    required this.rejected,
    required this.results,
  });

  final bool dryRun;
  final int created;
  final int updated;
  final int rejected;
  final List<ImportItemResult> results;

  /// Tolerant parse: skips malformed results, falls back to counting them.
  factory ImportResponse.fromJson(dynamic json) {
    final m = json is Map ? Map<String, dynamic>.from(json) : <String, dynamic>{};
    final raw = m['results'] is List ? m['results'] as List : const <Object?>[];
    final results = <ImportItemResult>[
      for (final e in raw)
        if (e is Map) ImportItemResult.fromJson(Map<String, dynamic>.from(e)),
    ];
    int count(String key, String action) {
      final v = m[key];
      if (v is num) return v.toInt();
      return results.where((r) => r.action == action).length;
    }

    return ImportResponse(
      dryRun: m['dry_run'] == true,
      created: count('created', 'created'),
      updated: count('updated', 'updated'),
      rejected: count('rejected', 'rejected'),
      results: results,
    );
  }
}
