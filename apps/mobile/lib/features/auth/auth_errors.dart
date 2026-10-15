import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:flutter/widgets.dart';

/// i18n key for auth errors that have a dedicated message, else null:
/// 409 account_exists, 401 invalid_credentials and 422 (rejected input).
String? authErrorKey(Object error) {
  if (error is! ApiException) return null;
  if (error.status == 409 || error.code == 'account_exists') {
    return 'auth.err.account_exists';
  }
  if (error.code == 'invalid_credentials') return 'auth.err.invalid_credentials';
  // The gateway's 422 (validation_error) does not say which field failed
  // (bad email / phone, or a password over 72 bytes), so one message covers it.
  if (error.status == 422 || error.code == 'validation_error') {
    return 'auth.err.invalid_input';
  }
  return null;
}

/// Localized text for a login / register / password error. 429 maps to the
/// "try later" message and names the wait when `Retry-After` was sent. With
/// [passwordFlow] the forgot / reset / change fallbacks apply.
String localizedAuthError(
  BuildContext context,
  Object error, {
  bool passwordFlow = false,
}) {
  if (error is ApiException && (error.status == 429 || error.code == 'rate_limited')) {
    return localizedError(context, error);
  }
  final key = authErrorKey(error);
  if (key != null) return context.tr(key);
  return passwordFlow
      ? localizedPasswordError(context, error)
      : localizedError(context, error);
}
