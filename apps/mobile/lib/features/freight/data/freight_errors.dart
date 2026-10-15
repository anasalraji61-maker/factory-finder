import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/widgets/offline.dart';
import 'package:flutter/widgets.dart';

/// Every error code the freight service can return (see contracts/openapi/freight.yaml).
const Set<String> kFreightErrorCodes = {
  'unauthenticated',
  'invalid_internal_token',
  'forbidden',
  'forwarder_required',
  'forwarder_suspended',
  'lane_mismatch',
  'own_request',
  'cannot_report_own',
  'not_found',
  'conflict',
  'already_awarded',
  'already_forwarder',
  'already_rated',
  'already_reviewed',
  'application_limit_reached',
  'application_pending',
  'request_limit_reached',
  'quote_limit_reached',
  'lane_limit_exceeded',
  'quote_exists',
  'quote_changed',
  'quote_expired',
  'quote_final',
  'quote_not_available',
  'quote_not_awarded',
  'request_expired',
  'request_not_open',
  'state_changed',
  'not_completed',
  'rating_too_early',
  'rating_pair_limit',
  'validation_error',
  'content_rejected',
  'currency_mismatch',
  'breakdown_mismatch',
  'invalid_cursor',
  'invalid_ready_date',
  'bad_request',
  'rate_limited',
};

/// i18n key + arguments describing [e].
class FreightErrorInfo {
  const FreightErrorInfo(this.key, [this.args = const {}]);

  final String key;
  final Map<String, String> args;

  @override
  String toString() => 'FreightErrorInfo($key, $args)';
}

/// Maps any failure to a localized message key. Known codes win; unknown
/// codes fall back to the HTTP status; network failures get their own text.
/// A 429 uses `Retry-After` (seconds) when the server sent it.
FreightErrorInfo freightErrorInfo(Object e) {
  if (e is! ApiException) {
    return isNetworkError(e)
        ? const FreightErrorInfo('freight.err.network')
        : const FreightErrorInfo('freight.err.generic');
  }
  if (isNetworkError(e)) return const FreightErrorInfo('freight.err.network');
  if (e.code == 'rate_limited' || e.status == 429) {
    final s = e.retryAfterSeconds;
    if (s != null && s > 0) {
      final mins = (s + 59) ~/ 60;
      return s >= 120
          ? FreightErrorInfo('freight.err.rate_limited_minutes', {'minutes': '$mins'})
          : FreightErrorInfo('freight.err.rate_limited_seconds', {'seconds': '$s'});
    }
    return const FreightErrorInfo('freight.err.rate_limited');
  }
  if (kFreightErrorCodes.contains(e.code)) {
    return FreightErrorInfo('freight.err.${e.code}');
  }
  switch (e.status) {
    case 401:
      return const FreightErrorInfo('freight.err.unauthenticated');
    case 403:
      return const FreightErrorInfo('freight.err.forbidden');
    case 404:
      return const FreightErrorInfo('freight.err.not_found');
    case 409:
      return const FreightErrorInfo('freight.err.conflict');
    case 422:
      return const FreightErrorInfo('freight.err.validation_error');
  }
  return const FreightErrorInfo('freight.err.generic');
}

String freightErrorKey(Object e) => freightErrorInfo(e).key;

extension FreightErrorText on BuildContext {
  /// Localized, user-facing text of a freight failure.
  String freightError(Object e) {
    final info = freightErrorInfo(e);
    return tr(info.key, info.args);
  }
}
