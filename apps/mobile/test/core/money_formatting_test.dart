import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/utils/number_format.dart';
import 'package:factory_finder/features/fx/data/fx_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Money currency precision', () {
    test('IQD and JPY have zero decimals', () {
      expect(const Money(amount: '1500000.00', currency: 'IQD').format(),
          'IQD 1,500,000');
      expect(const Money(amount: '1234.5', currency: 'JPY').format(),
          'JPY 1,235');
    });
    test('KWD has three decimals', () {
      expect(const Money(amount: '1234.5', currency: 'KWD').format(),
          'KWD 1,234.500');
      expect(const Money(amount: '0.0005', currency: 'KWD').format(),
          'KWD 0.001');
    });
    test('default is two decimals, symbols for USD/EUR', () {
      expect(const Money(amount: '5', currency: 'USD').format(), r'$5.00');
      expect(const Money(amount: '5', currency: 'EUR').format(), '€5.00');
      expect(const Money(amount: '5', currency: 'AED').format(), 'AED 5.00');
    });
  });

  group('exactness (no double)', () {
    test('values double cannot represent survive', () {
      // 2^53 + 1 is not representable as a double.
      expect(formatDecimalString('9007199254740993.10'),
          '9,007,199,254,740,993.10');
      expect(
          const Money(amount: '12345678901234567890.125', currency: 'USD')
              .format(),
          r'$12,345,678,901,234,567,890.13');
      expect(formatDecimalString('0.1000000000000000055511151231257827',
              fractionDigits: 3),
          '0.100');
    });
    test('formatFxString keeps exact digits', () {
      expect(formatFxString('9007199254740993'), '9,007,199,254,740,993');
    });
  });

  group('negatives and grouping', () {
    test('negative money puts sign before symbol or amount', () {
      expect(const Money(amount: '-5', currency: 'USD').format(), r'-$5.00');
      expect(const Money(amount: '-1234.5', currency: 'AED').format(),
          'AED -1,234.50');
      expect(const Money(amount: '-0.001', currency: 'USD').format(),
          r'$0.00');
    });
    test('large values group every three digits', () {
      expect(formatDecimalString('1000'), '1,000.00');
      expect(formatDecimalString('999'), '999.00');
      expect(formatDecimalString('1234567890123', fractionDigits: 0),
          '1,234,567,890,123');
      expect(formatDecimalString('1234567', grouping: false), '1234567.00');
    });
    test('input forms: leading zeros, bare dot parts, plus sign, commas', () {
      expect(formatDecimalString('0007.5'), '7.50');
      expect(formatDecimalString('.5'), '0.50');
      expect(formatDecimalString('5.'), '5.00');
      expect(formatDecimalString('+3'), '3.00');
      expect(formatDecimalString('1,234.5'), '1,234.50');
      expect(formatDecimalString('1e3'), '1,000.00');
    });
  });

  group('digit styles and RTL isolates', () {
    test('Arabic-Indic vs Western for a grouped amount', () {
      final s = const Money(amount: '1234567.5', currency: 'AED').format();
      expect(localizeNumber(s, DigitStyle.western), 'AED 1,234,567.50');
      expect(localizeNumber(s, DigitStyle.arabicIndic),
          'AED ١٬٢٣٤٬٥٦٧٫٥٠');
    });
    test('negative sign survives localization', () {
      expect(
          localizeNumber(
              const Money(amount: '-12.5', currency: 'USD').format(),
              DigitStyle.arabicIndic),
          r'-$١٢٫٥٠');
    });
    test('isolateLtr wraps in LRI/PDI and skips empty', () {
      expect(isolateLtr('USD 1'), '⁦USD 1⁩');
      expect(isolateLtr(''), '');
    });
    test('localized isolated money keeps its isolate marks', () {
      final iso = const Money(amount: '-1500', currency: 'IQD').formatIsolated();
      expect(iso, '⁦IQD -1,500⁩');
      expect(localizeNumber(iso, DigitStyle.arabicIndic),
          '⁦IQD -١٬٥٠٠⁩');
    });
    test('MoneyRange formats and isolates once', () {
      const r = MoneyRange(
        min: Money(amount: '10', currency: 'KWD'),
        max: Money(amount: '20', currency: 'KWD'),
      );
      expect(r.format(), 'KWD 10.000 – KWD 20.000');
      expect(r.formatIsolated(), '⁦KWD 10.000 – KWD 20.000⁩');
    });
    test('verbatim: nested and unbalanced markers do not leak', () {
      expect(verbatim(''), '');
      final s = '${verbatim('A1')} 2 ${verbatim('B3')} 4';
      expect(localizeDigits(s, DigitStyle.arabicIndic),
          '⁨A1⁩ ٢ ⁨B3⁩ ٤');
      // A stray PDI must not push depth negative and block conversion.
      expect(localizeDigits('⁩ 7', DigitStyle.arabicIndic), '⁩ ٧');
    });
  });

  group('dates', () {
    test('formatStamp converts local times to UTC and zero-pads', () {
      expect(formatStamp(DateTime.utc(2026, 1, 2, 3, 4)),
          '2026-01-02 03:04 UTC');
      expect(formatStamp(DateTime.parse('2026-10-13T23:59:00+03:00')),
          '2026-10-13 20:59 UTC');
    });
    test('formatStamp output localizes to Arabic-Indic digits', () {
      expect(
          localizeDigits(
              formatStamp(DateTime.utc(2026, 10, 13, 9, 5)), DigitStyle.arabicIndic),
          '٢٠٢٦-١٠-١٣ ٠٩:٠٥ UTC');
    });
  });
}
