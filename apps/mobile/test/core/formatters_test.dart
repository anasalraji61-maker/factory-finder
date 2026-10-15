import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/utils/number_format.dart';
import 'package:factory_finder/features/fx/data/fx_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('formatDecimalString', () {
    test('groups and pads', () {
      expect(formatDecimalString('1234.5'), '1,234.50');
      expect(formatDecimalString('1234567.891'), '1,234,567.89');
      expect(formatDecimalString('1500', fractionDigits: 0), '1,500');
    });
    test('rounds half-up on the string (no double drift)', () {
      expect(formatDecimalString('1.005'), '1.01');
      expect(formatDecimalString('9.995'), '10.00');
      expect(formatDecimalString('999999999999999999.999'),
          '1,000,000,000,000,000,000.00');
    });
    test('negative zero and unparsable input', () {
      expect(formatDecimalString('-0.001'), '0.00');
      expect(formatDecimalString('-1234.5'), '-1,234.50');
      expect(formatDecimalString('abc'), 'abc');
    });
  });

  group('Money', () {
    test('format keeps code before amount; isolate wraps it', () {
      const m = Money(amount: '1234.5', currency: 'TRY');
      expect(m.format(), 'TRY 1,234.50');
      expect(m.formatIsolated(), '⁦TRY 1,234.50⁩');
    });
  });

  group('digits', () {
    test('localizeDigits converts once and is idempotent', () {
      final once = localizeDigits('12 days', DigitStyle.arabicIndic);
      expect(once, '١٢ days');
      expect(localizeDigits(once, DigitStyle.arabicIndic), once);
    });
    test('localizeNumber swaps separators', () {
      expect(localizeNumber('1,234.50 USD', DigitStyle.arabicIndic),
          '١٬٢٣٤٫٥٠ USD');
      expect(localizeNumber('1,234.50 USD', DigitStyle.western),
          '1,234.50 USD');
    });
    test('verbatim ids keep ASCII digits, surrounding text converts', () {
      final s = 'حاوية ${verbatim('MSKU1234567')} بعد 5 أيام';
      expect(localizeDigits(s, DigitStyle.arabicIndic),
          'حاوية ⁨MSKU1234567⁩ بعد ٥ أيام');
      expect(localizeDigits(s, DigitStyle.western), s);
    });
    test('isolated money is still localized (different marker)', () {
      expect(
        localizeDigits(const Money(amount: '5', currency: 'USD').formatIsolated(),
            DigitStyle.arabicIndic),
        '\u2066\$٥.٠٠\u2069',
      );
    });
  });

  group('FX', () {
    test('formatFx grouping and negatives', () {
      expect(formatFx(-1234567.891), '-1,234,567.89');
      expect(formatFx(0.5), '0.5');
    });
    test('formatFxString is exact and trims zeros', () {
      expect(formatFxString('131000'), '131,000');
      expect(formatFxString('1310.005'), '1,310.01');
      expect(formatFxString('0.92'), '0.92');
      expect(formatFxString('1.50'), '1.5');
      expect(formatFxString('x'), '-');
    });
    test('formatStamp is UTC', () {
      expect(formatStamp(DateTime.utc(2026, 10, 13, 9, 5)),
          '2026-10-13 09:05 UTC');
      expect(formatStamp(null), '-');
    });
  });
}
