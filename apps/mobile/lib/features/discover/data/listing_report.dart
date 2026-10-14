import 'package:factory_finder/core/api/api_client.dart';

/// Max length of the free-text details (contract `maxLength`).
const int kReportDetailsMax = 500;

/// `reason` enum of POST /v1/listings/{id}/report.
enum ListingReportReason {
  prohibitedItem('prohibited_item'),
  counterfeit('counterfeit'),
  scamOrFraud('scam_or_fraud'),
  misleading('misleading'),
  contactInfoInListing('contact_info_in_listing'),
  offensive('offensive'),
  other('other');

  const ListingReportReason(this.json);
  final String json;
}

/// Request body; empty details are omitted.
Map<String, dynamic> buildReportBody(ListingReportReason reason, String? details) {
  var d = (details ?? '').trim();
  if (d.length > kReportDetailsMax) d = d.substring(0, kReportDetailsMax);
  return <String, dynamic>{
    'reason': reason.json,
    if (d.isNotEmpty) 'details': d,
  };
}

/// i18n key for a failed report (401/404/409/422/429 per the contract).
String reportErrorKey(Object error) {
  if (error is ApiException) {
    if (error.code == 'own_listing') return 'report.err.own_listing';
    switch (error.status) {
      case 401:
        return 'report.err.auth';
      case 404:
        return 'report.err.not_found';
      case 409:
        return 'report.err.own_listing';
      case 422:
        return 'report.err.invalid';
      case 429:
        return error.retryAfterSeconds != null
            ? 'report.err.rate_limited_wait'
            : 'report.err.rate_limited';
    }
    if (error.code == 'timeout' || error.code == 'network_error') {
      return 'report.err.network';
    }
  }
  return 'report.err.generic';
}

/// Minutes to show for a Retry-After value (at least 1).
int retryAfterMinutes(int seconds) => seconds <= 60 ? 1 : (seconds / 60).ceil();
