import 'dart:convert';

/// Per-service outcome inside an export bundle.
class ExportServiceStatus {
  const ExportServiceStatus({
    required this.name,
    required this.ok,
    this.error,
    this.truncated = false,
  });

  final String name;
  final bool ok;

  /// Short server code: timeout | unavailable | too_large | size_cap | ...
  final String? error;
  final bool truncated;
}

/// Parsed `GET /v1/me/export` bundle. Keeps the raw JSON so it can be copied.
class ExportResult {
  const ExportResult({
    required this.json,
    required this.sizeBytes,
    required this.partial,
    required this.services,
    this.generatedAt,
  });

  final Map<String, dynamic> json;
  final int sizeBytes;
  final bool partial;
  final String? generatedAt;
  final List<ExportServiceStatus> services;

  List<ExportServiceStatus> get failed =>
      [for (final s in services) if (!s.ok) s];

  List<ExportServiceStatus> get truncatedServices =>
      [for (final s in services) if (s.ok && s.truncated) s];

  /// Pretty JSON of the whole bundle.
  String toPrettyJson() => const JsonEncoder.withIndent('  ').convert(json);

  /// [rawBytes] is the transferred size when known (else re-encoded size).
  factory ExportResult.fromResponse(dynamic data, {int? rawBytes}) {
    Map<String, dynamic> map;
    var size = rawBytes;
    if (data is String) {
      size ??= utf8.encode(data).length;
      map = Map<String, dynamic>.from(jsonDecode(data) as Map);
    } else if (data is Map) {
      map = Map<String, dynamic>.from(data);
      size ??= utf8.encode(jsonEncode(map)).length;
    } else {
      throw const FormatException('Unexpected export payload');
    }
    final services = <ExportServiceStatus>[];
    final raw = map['services'];
    if (raw is Map) {
      for (final e in raw.entries) {
        final v = e.value;
        if (v is Map) {
          services.add(ExportServiceStatus(
            name: e.key.toString(),
            ok: v['status'] == 'ok',
            error: v['error'] is String ? v['error'] as String : null,
            truncated: v['truncated'] == true,
          ));
        }
      }
    }
    final anyFailed = services.any((s) => !s.ok);
    return ExportResult(
      json: map,
      sizeBytes: size,
      partial: map['partial'] == true || anyFailed,
      generatedAt:
          map['generated_at'] is String ? map['generated_at'] as String : null,
      services: services,
    );
  }
}

/// `scheduled` (grace period) | `partial` (some services retrying) | `deleted`.
class DeletionResult {
  const DeletionResult({
    required this.status,
    this.scheduledFor,
    this.deletedAt,
    this.services = const {},
  });

  final String status;
  final String? scheduledFor;
  final String? deletedAt;

  /// service name -> done | pending | failed
  final Map<String, String> services;

  bool get isDeleted => status == 'deleted';

  List<String> get pendingServices => [
        for (final e in services.entries)
          if (e.value != 'done') e.key,
      ];

  /// Date part (yyyy-mm-dd) of [scheduledFor], or null.
  String? get scheduledDate {
    final s = scheduledFor;
    if (s == null || s.length < 10) return null;
    return s.substring(0, 10);
  }

  factory DeletionResult.fromJson(dynamic json) {
    final m = json is Map ? Map<String, dynamic>.from(json) : <String, dynamic>{};
    final st = m['status'];
    final services = <String, String>{};
    final raw = m['services'];
    if (raw is Map) {
      raw.forEach((k, v) => services[k.toString()] = v.toString());
    }
    return DeletionResult(
      status: st is String && {'scheduled', 'partial', 'deleted'}.contains(st)
          ? st
          : 'partial',
      scheduledFor: m['scheduled_for'] as String?,
      deletedAt: m['deleted_at'] as String?,
      services: services,
    );
  }
}

/// Human readable size: `812 B`, `12.3 KB`, `4.8 MB`.
String formatByteSize(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}
