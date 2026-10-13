import 'package:factory_finder/core/api/api_client.dart';

final RegExp _supplierIdPattern = RegExp(r'^sup_[A-Za-z0-9_]+$');

/// True when [value] looks like a catalog supplier id (`sup_...`).
bool isValidSupplierId(String value) => _supplierIdPattern.hasMatch(value.trim());

/// i18n key for the validation error of [value], or null when valid.
String? supplierIdErrorKey(String value) =>
    isValidSupplierId(value) ? null : 'claim.err.format';

/// i18n key for a failed claim/release call.
String claimErrorKey(Object error) {
  if (error is ApiException && error.code == 'supplier_claimed') {
    return 'claim.err.taken';
  }
  return 'claim.err.generic';
}
