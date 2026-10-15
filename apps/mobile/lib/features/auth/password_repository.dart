import 'package:factory_finder/core/api/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Mock mode: this reset token is always rejected (400 invalid_token).
const String kMockInvalidResetToken = 'invalid-token';

/// Mock mode: this current password is always rejected.
const String kMockWrongPassword = 'wrong-password';

/// Mock mode: forgot-password for this email answers 429.
const String kMockRateLimitedEmail = 'limited@example.com';

/// Password recovery and change (gateway `/v1/auth/password/*`, `/v1/me/password`).
class PasswordRepository {
  PasswordRepository(this._api);

  final ApiClient _api;

  /// Always completes the same way for any email (the server answers 202
  /// whether or not the account exists). Throws only on 429 / 422 / network.
  Future<void> forgot(String email) async {
    if (_api.isMock) {
      await mockDelay(200);
      if (email.trim().toLowerCase() == kMockRateLimitedEmail) {
        throw ApiException(
          status: 429,
          code: 'rate_limited',
          message: 'Too many requests',
          retryAfterSeconds: 60,
        );
      }
      return;
    }
    await _api.post(
      '/v1/auth/password/forgot',
      auth: false,
      body: forgotBody(email),
    );
  }

  Future<void> reset({required String token, required String newPassword}) async {
    if (_api.isMock) {
      await mockDelay(200);
      if (token.trim() == kMockInvalidResetToken) {
        throw ApiException(
          status: 400,
          code: 'invalid_token',
          message: 'Invalid or expired token',
        );
      }
      return;
    }
    await _api.post(
      '/v1/auth/password/reset',
      auth: false,
      body: resetBody(token, newPassword),
    );
  }

  Future<void> change({
    required String currentPassword,
    required String newPassword,
  }) async {
    if (_api.isMock) {
      await mockDelay(200);
      if (currentPassword == kMockWrongPassword) {
        throw ApiException(
          status: 400,
          code: 'invalid_current_password',
          message: 'Current password is wrong',
        );
      }
      return;
    }
    final json = await _api.post(
      '/v1/me/password',
      body: changeBody(currentPassword, newPassword),
    );
    // The server revoked every refresh token and answers with a fresh pair for
    // this device: store it so the session survives. Tolerate an empty body.
    if (json is Map) {
      final access = json['access_token'];
      final refresh = json['refresh_token'];
      if (access is String && access.isNotEmpty) {
        _api.tokens.set(access, refresh is String ? refresh : null);
      }
    }
  }
}

Map<String, dynamic> forgotBody(String email) =>
    <String, dynamic>{'email': email.trim()};

Map<String, dynamic> resetBody(String token, String newPassword) =>
    <String, dynamic>{'token': token.trim(), 'new_password': newPassword};

Map<String, dynamic> changeBody(String currentPassword, String newPassword) =>
    <String, dynamic>{
      'current_password': currentPassword,
      'new_password': newPassword,
    };

final passwordRepositoryProvider = Provider<PasswordRepository>(
  (ref) => PasswordRepository(ref.watch(apiClientProvider)),
);
