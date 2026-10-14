// Supplier business verification (contracts/openapi/trust.yaml, verification
// paths). Pure Dart (no Flutter imports) so parsing and validation are
// unit-testable.

import 'package:factory_finder/core/api/api_client.dart';

/// Contract enum DocType.
const List<String> kVerificationDocTypes = [
  'business_license',
  'company_registry_reference',
  'bank_reference',
  'export_license',
  'factory_photos',
  'iso_certificate',
  'other_certificate',
];

/// The only type that carries no number (the server rejects a number for it).
const String kUnnumberedDocType = 'factory_photos';

/// Contract enum verification_level, lowest first.
const List<String> kVerificationLevels = ['none', 'basic', 'documented', 'audited'];

const int kVerificationMaxFiles = 10;
const int kVerificationNumberMin = 4;
const int kVerificationNumberMax = 64;

bool docTypeNeedsNumber(String? docType) => docType != kUnnumberedDocType;

/// Unknown or missing levels degrade to `none`.
String normalizeVerificationLevel(Object? raw) {
  final v = raw?.toString().trim().toLowerCase();
  return kVerificationLevels.contains(v) ? v! : 'none';
}

/// Display status of a document: an approved but expired one shows as expired.
String effectiveDocStatus(VerificationDocument d) =>
    d.status == 'approved' && d.isExpired ? 'expired' : d.status;

/// Pending and approved documents may be withdrawn.
bool canWithdraw(VerificationDocument d) =>
    d.status == 'pending' || d.status == 'approved';

class VerificationDocument {
  const VerificationDocument({
    required this.id,
    required this.docType,
    required this.issuingCountry,
    required this.status,
    this.files = const <String>[],
    this.numberMasked,
    this.expiresOn,
    this.isExpired = false,
    this.reason,
    this.createdAt,
    this.reviewedAt,
  });

  final String id;
  final String docType;
  final String issuingCountry;
  final List<String> files;

  /// `****` plus at most the last 4 characters; never the full number.
  final String? numberMasked;

  /// `yyyy-MM-dd` as sent by the server.
  final String? expiresOn;
  final String status;
  final bool isExpired;
  final String? reason;
  final DateTime? createdAt;
  final DateTime? reviewedAt;

  factory VerificationDocument.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    String? text(Object? v) {
      final s = v?.toString().trim();
      return s == null || s.isEmpty ? null : s;
    }

    final rawFiles = m['files'];
    final status = (text(m['status']) ?? 'pending').toLowerCase();
    return VerificationDocument(
      id: text(m['id']) ?? '',
      docType: text(m['doc_type']) ?? 'other_certificate',
      issuingCountry: (text(m['issuing_country']) ?? '').toUpperCase(),
      files: rawFiles is List
          ? [for (final f in rawFiles) if (f is String) f]
          : const <String>[],
      numberMasked: text(m['number_masked']),
      expiresOn: text(m['expires_on']),
      status: status,
      isExpired: m['is_expired'] == true,
      reason: text(m['reason']),
      createdAt: DateTime.tryParse(m['created_at']?.toString() ?? ''),
      reviewedAt: DateTime.tryParse(m['reviewed_at']?.toString() ?? ''),
    );
  }
}

class VerificationList {
  const VerificationList({required this.items, required this.level});

  final List<VerificationDocument> items;
  final String level;

  /// Skips malformed rows; a missing level is `none`.
  factory VerificationList.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    final raw = m['items'];
    return VerificationList(
      items: raw is List
          ? [
              for (final e in raw)
                if (e is Map && e['id'] != null) VerificationDocument.fromJson(e),
            ]
          : const <VerificationDocument>[],
      level: normalizeVerificationLevel(m['verification_level']),
    );
  }
}

/// Public badge: level and valid document types only.
class PublicVerification {
  const PublicVerification({
    required this.supplierId,
    required this.level,
    this.label = '',
    this.labelAr = '',
    this.validTypes = const <String>[],
  });

  final String supplierId;
  final String level;
  final String label;
  final String labelAr;
  final List<String> validTypes;

  bool get isVerified => level != 'none';

  String display(String lang) {
    final primary = lang == 'ar' ? labelAr : label;
    if (primary.trim().isNotEmpty) return primary;
    return lang == 'ar' ? label : labelAr;
  }

  factory PublicVerification.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    final types = m['valid_types'];
    return PublicVerification(
      supplierId: m['supplier_id']?.toString() ?? '',
      level: normalizeVerificationLevel(m['verification_level']),
      label: m['label']?.toString() ?? '',
      labelAr: m['label_ar']?.toString() ?? '',
      validTypes: types is List
          ? [for (final t in types) if (t is String) t]
          : const <String>[],
    );
  }
}

/// What the supplier typed/picked. [files] are media-service paths.
class VerificationDraft {
  const VerificationDraft({
    this.docType,
    this.country = '',
    this.number = '',
    this.expiresOn = '',
    this.consent = false,
    this.files = const <String>[],
  });

  final String? docType;
  final String country;
  final String number;

  /// `yyyy-MM-dd` or empty.
  final String expiresOn;
  final bool consent;
  final List<String> files;

  /// Request body of POST /v1/trust/verification/documents.
  Map<String, dynamic> toJson() {
    final n = number.trim();
    final e = expiresOn.trim();
    return <String, dynamic>{
      'doc_type': docType,
      'issuing_country': country.trim().toUpperCase(),
      'files': files,
      if (docTypeNeedsNumber(docType) && n.isNotEmpty) 'number': n,
      if (e.isNotEmpty) 'expires_on': e,
      'consent': consent,
    };
  }
}

final RegExp _datePattern = RegExp(r'^\d{4}-\d{2}-\d{2}$');
final RegExp _countryPattern = RegExp(r'^[A-Za-z]{2}$');

/// Parses a strict `yyyy-MM-dd` calendar date (rejects 2026-02-31); null otherwise.
DateTime? parseIsoDate(String value) {
  final v = value.trim();
  if (!_datePattern.hasMatch(v)) return null;
  final y = int.parse(v.substring(0, 4));
  final mo = int.parse(v.substring(5, 7));
  final d = int.parse(v.substring(8, 10));
  final dt = DateTime.utc(y, mo, d);
  if (dt.year != y || dt.month != mo || dt.day != d) return null;
  return dt;
}

String formatIsoDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// Field name -> i18n key. Empty map means valid. Fields: type, country,
/// number, expiry, consent, files.
Map<String, String> validateVerificationDraft(VerificationDraft d, {DateTime? today}) {
  final errors = <String, String>{};
  if (d.docType == null || !kVerificationDocTypes.contains(d.docType)) {
    errors['type'] = 'ver.err.type';
  }
  if (!_countryPattern.hasMatch(d.country.trim())) {
    errors['country'] = 'ver.err.country';
  }
  if (docTypeNeedsNumber(d.docType)) {
    final n = d.number.trim().length;
    if (n < kVerificationNumberMin || n > kVerificationNumberMax) {
      errors['number'] = 'ver.err.number';
    }
  }
  final exp = d.expiresOn.trim();
  if (exp.isNotEmpty) {
    final parsed = parseIsoDate(exp);
    final now = today ?? DateTime.now();
    final t = DateTime.utc(now.year, now.month, now.day);
    if (parsed == null) {
      errors['expiry'] = 'ver.err.expiry_format';
    } else if (parsed.isBefore(t)) {
      errors['expiry'] = 'ver.err.expiry_past';
    }
  }
  if (d.files.isEmpty || d.files.length > kVerificationMaxFiles) {
    errors['files'] = 'ver.err.files';
  }
  if (!d.consent) errors['consent'] = 'ver.err.consent';
  return errors;
}

/// i18n key for a failed verification call (contract error codes first, then
/// HTTP status).
String verificationErrorKey(Object error) {
  if (error is! ApiException) return 'ver.err.generic';
  switch (error.code) {
    case 'supplier_required':
    case 'supplier_verification_required':
      return 'ver.err.supplier_required';
    case 'consent_required':
      return 'ver.err.consent';
    case 'already_expired':
      return 'ver.err.expiry_past';
    case 'number_required':
      return 'ver.err.number';
    case 'number_not_allowed':
      return 'ver.err.number_not_allowed';
    case 'invalid_files':
      return 'ver.err.files';
    case 'file_url_not_allowed':
      return 'ver.err.file_url';
    case 'invalid_doc_type':
      return 'ver.err.type';
    case 'duplicate_document':
      return 'ver.err.duplicate';
    case 'document_limit_reached':
      return 'ver.err.limit';
    case 'document_type_limit_reached':
      return 'ver.err.type_limit';
    case 'invalid_transition':
      return 'ver.err.transition';
    case 'document_not_found':
      return 'ver.err.not_found';
    case 'capacity_reached':
      return 'ver.err.capacity';
    case 'rate_limited':
      return _rateKey(error);
    case 'timeout':
    case 'network_error':
      return 'ver.err.network';
  }
  switch (error.status) {
    case 401:
      return 'ver.err.supplier_required';
    case 429:
      return _rateKey(error);
    case 404:
      return 'ver.err.not_found';
  }
  return 'ver.err.generic';
}

String _rateKey(ApiException e) {
  final wait = e.retryAfterSeconds;
  return wait != null && wait > 0 ? 'ver.err.rate_limited_wait' : 'ver.err.rate_limited';
}

/// Template args for [verificationErrorKey] (minutes to wait, at least 1).
Map<String, String> verificationErrorArgs(Object error) {
  if (error is ApiException) {
    final wait = error.retryAfterSeconds;
    if (wait != null && wait > 0) return {'n': '${(wait + 59) ~/ 60}'};
  }
  return const <String, String>{};
}
