/// Exact formatting of decimal strings (money amounts arrive as strings such as
/// "1234.5" — see CLAUDE.md rule 8). No binary floating point is involved
/// unless the input is not a plain decimal (e.g. "1e3"), in which case we fall
/// back to `double` parsing.
library;

final RegExp _digits = RegExp(r'^[0-9]*$');

/// Formats [raw] with thousands [grouping] and exactly [fractionDigits]
/// decimals, rounding half-up on the decimal string itself.
///
/// ```
/// formatDecimalString('1234.5')    // '1,234.50'
/// formatDecimalString('9.995')     // '10.00'
/// formatDecimalString('-0.001')    // '0.00'
/// formatDecimalString('1500', fractionDigits: 0) // '1,500'
/// ```
/// Returns [raw] unchanged when it is not a number at all.
String formatDecimalString(
  String raw, {
  int fractionDigits = 2,
  bool grouping = true,
}) {
  final decimals = fractionDigits < 0 ? 0 : fractionDigits;
  var s = raw.trim().replaceAll(',', '');
  var negative = false;
  if (s.startsWith('-')) {
    negative = true;
    s = s.substring(1);
  } else if (s.startsWith('+')) {
    s = s.substring(1);
  }

  final dot = s.indexOf('.');
  var intPart = dot < 0 ? s : s.substring(0, dot);
  var fracPart = dot < 0 ? '' : s.substring(dot + 1);

  final isPlainDecimal = s.isNotEmpty &&
      s != '.' &&
      _digits.hasMatch(intPart) &&
      _digits.hasMatch(fracPart);
  if (!isPlainDecimal) {
    final parsed = double.tryParse(raw.trim());
    if (parsed == null || parsed.isNaN || parsed.isInfinite) return raw;
    final fixed = parsed.toStringAsFixed(decimals);
    if (fixed.contains('e')) return fixed;
    return formatDecimalString(
      fixed,
      fractionDigits: decimals,
      grouping: grouping,
    );
  }

  if (intPart.isEmpty) intPart = '0';

  if (fracPart.length > decimals) {
    final roundUp = fracPart.codeUnitAt(decimals) >= 0x35; // '5'
    fracPart = fracPart.substring(0, decimals);
    if (roundUp) {
      final digits = '$intPart$fracPart'.codeUnits.map((c) => c - 0x30).toList();
      var i = digits.length - 1;
      while (i >= 0) {
        if (digits[i] == 9) {
          digits[i] = 0;
          i--;
        } else {
          digits[i]++;
          break;
        }
      }
      var joined = digits.join();
      if (i < 0) joined = '1$joined';
      intPart = joined.substring(0, joined.length - decimals);
      fracPart = joined.substring(joined.length - decimals);
    }
  } else {
    fracPart = fracPart.padRight(decimals, '0');
  }

  intPart = intPart.replaceFirst(RegExp(r'^0+(?=[0-9])'), '');
  if (intPart.isEmpty) intPart = '0';

  final grouped = grouping ? _group(intPart) : intPart;
  final isZero =
      !intPart.contains(RegExp('[1-9]')) && !fracPart.contains(RegExp('[1-9]'));
  final sign = negative && !isZero ? '-' : '';
  return decimals == 0 ? '$sign$grouped' : '$sign$grouped.$fracPart';
}

String _group(String digits) {
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return buffer.toString();
}
