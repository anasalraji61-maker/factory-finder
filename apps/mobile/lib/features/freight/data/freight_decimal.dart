/// Exact decimal handling for freight money / quantities (CLAUDE.md rule 8).
///
/// Values are parsed to scaled integers ("12.50" at scale 2 -> 1250) so sums
/// and comparisons never touch binary floating point.
library;

class FreightDecimal {
  FreightDecimal._();

  static final RegExp _plain = RegExp(r'^\d{1,12}(\.\d+)?$');

  /// Converts user input to a plain ASCII decimal ("1234.5"), or null when it
  /// is not one. Accepts Arabic-Indic / Persian digits, the Arabic decimal
  /// separator and a single decimal comma; strips grouping separators.
  static String? normalize(String raw) {
    final b = StringBuffer();
    for (final unit in raw.trim().codeUnits) {
      if (unit >= 0x660 && unit <= 0x669) {
        b.writeCharCode(0x30 + unit - 0x660);
      } else if (unit >= 0x6F0 && unit <= 0x6F9) {
        b.writeCharCode(0x30 + unit - 0x6F0);
      } else if (unit == 0x66B) {
        b.write('.');
      } else if (unit == 0x66C || unit == 0x20 || unit == 0xA0) {
        // grouping separators / spaces are dropped
      } else {
        b.writeCharCode(unit);
      }
    }
    var s = b.toString();
    if (!s.contains('.') && ','.allMatches(s).length == 1) {
      s = s.replaceFirst(',', '.');
    } else {
      s = s.replaceAll(',', '');
    }
    return _plain.hasMatch(s) ? s : null;
  }

  /// Scaled integer of [raw] (already ASCII or user input), or null when it
  /// is not a plain non-negative decimal or has more than [scale] decimals.
  static int? parseScaled(String raw, int scale) {
    final s = normalize(raw);
    if (s == null) return null;
    final dot = s.indexOf('.');
    final intPart = dot < 0 ? s : s.substring(0, dot);
    final frac = dot < 0 ? '' : s.substring(dot + 1);
    if (frac.length > scale) return null;
    return int.tryParse('$intPart${frac.padRight(scale, '0')}');
  }

  /// "1250" at scale 2 -> "12.50".
  static String formatScaled(int units, int scale) {
    final negative = units < 0;
    var digits = (negative ? -units : units).toString();
    if (scale == 0) return '${negative ? '-' : ''}$digits';
    digits = digits.padLeft(scale + 1, '0');
    final head = digits.substring(0, digits.length - scale);
    final tail = digits.substring(digits.length - scale);
    return '${negative ? '-' : ''}$head.$tail';
  }

  /// User input -> canonical wire string with exactly [scale] decimals
  /// ("12.5" -> "12.50"), or null when invalid.
  static String? canonical(String raw, int scale) {
    final units = parseScaled(raw, scale);
    return units == null ? null : formatScaled(units, scale);
  }

  /// Wire value (string or JSON number) -> trimmed string, or null.
  static String? wire(Object? v) {
    if (v == null) return null;
    final s = v.toString().trim();
    return s.isEmpty ? null : s;
  }

  /// Sum of already-validated [amounts] at [scale]; null when any is invalid.
  static int? sumScaled(Iterable<String> amounts, int scale) {
    var total = 0;
    for (final a in amounts) {
      final u = parseScaled(a, scale);
      if (u == null) return null;
      total += u;
    }
    return total;
  }

  /// A double (e.g. from the calculator) as a decimal string with at most
  /// [scale] decimals, trailing zeros trimmed ("12.500" -> "12.5").
  static String fromDouble(double v, int scale) {
    var s = v.toStringAsFixed(scale);
    if (s.contains('.')) {
      s = s.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
    }
    return s.isEmpty ? '0' : s;
  }
}
