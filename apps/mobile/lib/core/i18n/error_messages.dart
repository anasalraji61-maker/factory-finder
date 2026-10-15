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
  'upstream_timeout': 'error.upstream_timeout',
};

/// i18n key for [error] when its code is a known backend code, else null.
String? apiErrorKey(Object error) =>
    error is ApiException ? kApiErrorKeys[error.code] : null;

/// Localized text for [error]: the mapped message for known codes, otherwise
/// [describeError].
String localizedError(BuildContext context, Object error) {
  final key = apiErrorKey(error);
  return key == null ? describeError(error) : context.tr(key);
}
