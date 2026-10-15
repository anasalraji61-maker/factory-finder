import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/privacy/privacy_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Mock mode: this password fails re-auth with 403 `reauth_failed`.
const String kMockWrongPassword = 'wrong-password';

/// Mock mode: this password yields a 202-style partial deletion.
const String kMockPartialPassword = 'partial-password';

abstract class PrivacyRepository {
  Future<ExportResult> exportData();

  /// Exactly one of [password] / [refreshToken] should be given.
  Future<DeletionResult> deleteAccount({String? password, String? refreshToken});
}

class LivePrivacyRepository implements PrivacyRepository {
  LivePrivacyRepository(this._api);
  final ApiClient _api;

  @override
  Future<ExportResult> exportData() async =>
      ExportResult.fromResponse(await _api.get('/v1/me/export'));

  @override
  Future<DeletionResult> deleteAccount({
    String? password,
    String? refreshToken,
  }) async {
    final body = <String, dynamic>{
      if (password != null) 'password': password,
      if (password == null && refreshToken != null) 'refresh_token': refreshToken,
    };
    return DeletionResult.fromJson(await _api.delete('/v1/me', body: body));
  }
}

class MockPrivacyRepository implements PrivacyRepository {
  @override
  Future<ExportResult> exportData() async {
    await mockDelay(150);
    return ExportResult.fromResponse(<String, dynamic>{
      'format_version': 1,
      'generated_at': '2026-10-15T09:00:00Z',
      'partial': false,
      'user': <String, dynamic>{'id': 'usr_mock', 'name': 'user'},
      'services': <String, dynamic>{
        'gateway': <String, dynamic>{'status': 'ok', 'data': <String, dynamic>{}},
        'rfq': <String, dynamic>{'status': 'ok', 'data': <String, dynamic>{}},
      },
    });
  }

  @override
  Future<DeletionResult> deleteAccount({
    String? password,
    String? refreshToken,
  }) async {
    await mockDelay(200);
    if (password == kMockWrongPassword) {
      throw ApiException(
        status: 403,
        code: 'reauth_failed',
        message: 'Re-authentication failed',
      );
    }
    if (password == kMockPartialPassword) {
      return const DeletionResult(
        status: 'partial',
        services: {'gateway': 'done', 'messaging': 'pending'},
      );
    }
    return const DeletionResult(
      status: 'deleted',
      deletedAt: '2026-10-15T09:00:00Z',
      services: {'gateway': 'done', 'messaging': 'done'},
    );
  }
}

final privacyRepositoryProvider = Provider<PrivacyRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockPrivacyRepository() : LivePrivacyRepository(api);
});

/// i18n key for an error from export / delete. Pure, unit tested.
String privacyErrorKey(Object e) {
  if (e is ApiException) {
    if (e.code == 'reauth_failed') return 'privacy.err.reauth_failed';
    switch (e.status) {
      case 403:
        return 'privacy.err.forbidden';
      case 429:
        return 'privacy.err.rate_limited';
      case 401:
        return 'privacy.err.session';
      case 422:
        return 'privacy.err.invalid';
    }
    if (e.code == 'network_error' || e.code == 'timeout') {
      return 'privacy.err.network';
    }
    if (e.status != null && e.status! >= 500) return 'privacy.err.server';
  }
  return 'privacy.err.generic';
}
