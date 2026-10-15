import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:flutter/widgets.dart';

/// Backend error codes that have a dedicated localized message.
const Map<String, String> kApiErrorKeys = {
  'file_in_use': 'error.file_in_use',
  'rating_too_early': 'error.rating_too_early',
  'rating_pair_limit': 'error.rating_pair_limit',
  'too_many_open_invoices': 'error.too_many_open_invoices',
  'daily_invoice_limit': 'error.daily_invoice_limit',
  'conversation_limit_reached': 'error.conversation_limit_reached',
  'conversation_full': 'error.conversation_full',
  'user_blocked': 'error.user_blocked',
  'upstream_timeout': 'error.upstream_timeout',
  'rate_limited': 'error.rate_limited',
  'invalid_token': 'error.invalid_token',
  'invalid_reset_token': 'error.invalid_token',
  'reauth_failed': 'error.invalid_current_password',
  'invalid_current_password': 'error.invalid_current_password',
  'weak_password': 'error.weak_password',
};

/// i18n key for [error] when its code is a known backend code, else null.
String? apiErrorKey(Object error) =>
    error is ApiException ? kApiErrorKeys[error.code] : null;

/// Localized text for [error]: the mapped message for known codes, otherwise
/// [describeError].
String localizedError(BuildContext context, Object error) {
  if (error is ApiException && (error.status == 429 || error.code == 'rate_limited')) {
    final s = error.retryAfterSeconds;
    if (s != null && s > 0) {
      return context.tr('error.rate_limited_wait', {'n': '${s <= 60 ? 1 : (s / 60).ceil()}'});
    }
    return context.tr('error.rate_limited');
  }
  final key = apiErrorKey(error);
  return key == null ? describeError(error) : context.tr(key);
}

/// i18n key for password/auth flows: the code mapping first, then HTTP status
/// fallbacks (429 too many requests, 422 rejected input), else null.
String? passwordErrorKey(Object error) {
  final byCode = apiErrorKey(error);
  if (byCode != null) return byCode;
  if (error is ApiException) {
    if (error.status == 429) return 'error.rate_limited';
    if (error.status == 422) return 'error.weak_password';
  }
  return null;
}

/// Localized text for an error from the forgot / reset / change password
/// calls. A 429 with Retry-After names the wait in minutes.
String localizedPasswordError(BuildContext context, Object error) {
  final key = passwordErrorKey(error);
  if (key == null) return describeError(error);
  if (key == 'error.rate_limited' &&
      error is ApiException &&
      error.retryAfterSeconds != null) {
    final s = error.retryAfterSeconds!;
    final minutes = s <= 60 ? 1 : (s / 60).ceil();
    return context.tr('error.rate_limited_wait', {'n': '$minutes'});
  }
  return context.tr(key);
}
