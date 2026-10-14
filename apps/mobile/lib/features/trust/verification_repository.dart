import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class VerificationRepository {
  /// Own documents and badge level. Throws [ApiException] (401 not a verified supplier).
  Future<VerificationList> listMine();

  /// Throws [ApiException] (401, 409 duplicate/cap, 422 invalid, 429 rate limited).
  Future<VerificationDocument> submit(VerificationDraft draft);

  /// Throws [ApiException] (404 unknown id, 409 not withdrawable).
  Future<VerificationDocument> withdraw(String documentId);

  /// Public badge of any supplier. Throws [ApiException] (404, 503).
  Future<PublicVerification> publicBadge(String supplierId);
}

class LiveVerificationRepository implements VerificationRepository {
  LiveVerificationRepository(this._api);
  final ApiClient _api;

  @override
  Future<VerificationList> listMine() async =>
      VerificationList.fromJson(await _api.get('/v1/trust/verification/documents'));

  @override
  Future<VerificationDocument> submit(VerificationDraft draft) async =>
      VerificationDocument.fromJson(
        await _api.post('/v1/trust/verification/documents', body: draft.toJson()),
      );

  @override
  Future<VerificationDocument> withdraw(String documentId) async =>
      VerificationDocument.fromJson(
        await _api.delete(
          '/v1/trust/verification/documents/${Uri.encodeComponent(documentId)}',
        ),
      );

  @override
  Future<PublicVerification> publicBadge(String supplierId) async =>
      PublicVerification.fromJson(
        await _api.get(
          '/v1/trust/suppliers/${Uri.encodeComponent(supplierId)}/verification',
          auth: false,
        ),
      );
}

/// Deterministic in-memory backend: no network, no timers.
class MockVerificationRepository implements VerificationRepository {
  MockVerificationRepository({this.maxSubmissions = 10, DateTime? now})
      : _now = now ?? DateTime.utc(2026, 10, 1) {
    _docs.addAll([
      VerificationDocument(
        id: 'vdoc_mock_1',
        docType: 'business_license',
        issuingCountry: 'IQ',
        files: const ['/v1/media/files/mock0000000000000000000000000001.jpg'],
        numberMasked: '****5678',
        expiresOn: '2030-01-01',
        status: 'approved',
        createdAt: _now,
        reviewedAt: _now,
      ),
      VerificationDocument(
        id: 'vdoc_mock_2',
        docType: 'bank_reference',
        issuingCountry: 'IQ',
        files: const ['/v1/media/files/mock0000000000000000000000000002.jpg'],
        numberMasked: '****',
        status: 'rejected',
        reason: 'The document is not legible',
        createdAt: _now,
        reviewedAt: _now,
      ),
    ]);
  }

  final int maxSubmissions;
  final DateTime _now;
  final List<VerificationDocument> _docs = [];
  int _seq = 2;
  int _submitted = 0;

  String get _level {
    final ok = _docs.where((d) => d.status == 'approved' && !d.isExpired);
    final types = ok.map((d) => d.docType).toSet();
    if (types.length >= 2) return 'documented';
    return types.isEmpty ? 'none' : 'basic';
  }

  @override
  Future<VerificationList> listMine() async =>
      VerificationList(items: List.of(_docs.reversed), level: _level);

  @override
  Future<VerificationDocument> submit(VerificationDraft draft) async {
    if (_submitted >= maxSubmissions) {
      throw ApiException(
        status: 429,
        code: 'rate_limited',
        message: 'Too many submissions',
        retryAfterSeconds: 600,
      );
    }
    final number = draft.number.trim().toUpperCase();
    final dup = _docs.any((d) =>
        (d.status == 'pending' || d.status == 'approved') &&
        d.docType == draft.docType &&
        d.issuingCountry == draft.country.trim().toUpperCase() &&
        d.numberMasked == _mask(number));
    if (dup) {
      throw ApiException(
        status: 409,
        code: 'duplicate_document',
        message: 'This document was already submitted',
      );
    }
    _submitted++;
    _seq++;
    final doc = VerificationDocument(
      id: 'vdoc_mock_$_seq',
      docType: draft.docType ?? 'other_certificate',
      issuingCountry: draft.country.trim().toUpperCase(),
      files: List.of(draft.files),
      numberMasked: docTypeNeedsNumber(draft.docType) ? _mask(number) : null,
      expiresOn: draft.expiresOn.trim().isEmpty ? null : draft.expiresOn.trim(),
      status: 'pending',
      createdAt: _now,
    );
    _docs.add(doc);
    return doc;
  }

  static String _mask(String norm) {
    final n = norm.replaceAll(RegExp(r'[^A-Z0-9]'), '');
    return n.length >= 8 ? '****${n.substring(n.length - 4)}' : '****';
  }

  @override
  Future<VerificationDocument> withdraw(String documentId) async {
    final i = _docs.indexWhere((d) => d.id == documentId);
    if (i < 0) {
      throw ApiException(status: 404, code: 'document_not_found', message: 'Document not found');
    }
    final d = _docs[i];
    if (!canWithdraw(d)) {
      throw ApiException(
        status: 409,
        code: 'invalid_transition',
        message: 'Cannot move a ${d.status} document to withdrawn',
      );
    }
    final out = VerificationDocument(
      id: d.id,
      docType: d.docType,
      issuingCountry: d.issuingCountry,
      files: d.files,
      numberMasked: d.numberMasked,
      expiresOn: d.expiresOn,
      status: 'withdrawn',
      isExpired: d.isExpired,
      reason: d.reason,
      createdAt: d.createdAt,
      reviewedAt: d.reviewedAt,
    );
    _docs[i] = out;
    return out;
  }

  @override
  Future<PublicVerification> publicBadge(String supplierId) async {
    final seed = supplierId.codeUnits.fold<int>(0, (a, b) => (a + b) % 4);
    final level = kVerificationLevels[seed];
    return PublicVerification(
      supplierId: supplierId,
      level: level,
      label: 'Verified business ($level)',
      labelAr: '',
      validTypes: level == 'none' ? const <String>[] : const ['business_license'],
    );
  }
}

final verificationRepositoryProvider = Provider<VerificationRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockVerificationRepository() : LiveVerificationRepository(api);
});

/// Own documents (verified suppliers only).
final myVerificationProvider = FutureProvider.autoDispose<VerificationList>(
  (ref) => ref.watch(verificationRepositoryProvider).listMine(),
);

/// Public badge; null when the endpoint is absent/unavailable so callers can
/// simply render nothing.
final supplierVerificationProvider =
    FutureProvider.autoDispose.family<PublicVerification?, String>((ref, id) async {
  try {
    return await ref.watch(verificationRepositoryProvider).publicBadge(id);
  } catch (_) {
    return null;
  }
});
