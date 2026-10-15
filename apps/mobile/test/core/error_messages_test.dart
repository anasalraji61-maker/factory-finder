import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('every mapped backend code has ar and en text', () {
    for (final entry in kApiErrorKeys.entries) {
      final ex = ApiException(status: 409, code: entry.key, message: 'raw');
      expect(apiErrorKey(ex), entry.value);
      final ar = AppStrings.lookup('ar', entry.value);
      final en = AppStrings.lookup('en', entry.value);
      expect(ar, isNot(entry.value), reason: entry.key);
      expect(en, isNot(entry.value), reason: entry.key);
      expect(ar, isNot(en));
    }
    expect(kApiErrorKeys.keys, containsAll(<String>[
      'file_in_use',
      'rating_too_early',
      'rating_pair_limit',
      'too_many_open_invoices',
      'daily_invoice_limit',
      'conversation_limit_reached',
      'conversation_full',
      'upstream_timeout',
    ]));
  });

  test('unknown codes and non-API errors are not mapped', () {
    expect(apiErrorKey(ApiException(code: 'server_error', message: 'x')), isNull);
    expect(apiErrorKey(StateError('x')), isNull);
  });
}
