import 'package:factory_finder/features/tracking/data/tracking_models.dart';

/// Client-side reference validation. Each function returns `null` when valid or
/// an i18n key describing the problem (shown with `context.tr`).

String normalizeReference(String input) =>
    input.toUpperCase().replaceAll(RegExp(r'[\s\-]'), '');

/// ISO 6346 letter values: A=10, B=12 ... (multiples of 11 are skipped).
final Map<String, int> _letterValues = () {
  final map = <String, int>{};
  var n = 10;
  for (final code in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.codeUnits) {
    if (n % 11 == 0) n++;
    map[String.fromCharCode(code)] = n++;
  }
  return map;
}();

/// Computes the ISO 6346 check digit for the first 10 characters.
int containerCheckDigit(String first10) {
  var sum = 0;
  for (var i = 0; i < 10; i++) {
    final ch = first10[i];
    final v = _letterValues[ch] ?? int.parse(ch);
    sum += v * (1 << i);
  }
  return sum % 11 % 10;
}

String? validateContainer(String input) {
  final s = normalizeReference(input);
  if (!RegExp(r'^[A-Z]{3}[UJZ][0-9]{7}$').hasMatch(s)) {
    return 'tracking.err.container_format';
  }
  if (containerCheckDigit(s.substring(0, 10)) != int.parse(s[10])) {
    return 'tracking.err.container_check';
  }
  return null;
}

/// AWB: 3-digit airline prefix + 8-digit serial; last digit = first 7 serial digits mod 7.
String? validateAwb(String input) {
  final s = normalizeReference(input);
  if (!RegExp(r'^[0-9]{11}$').hasMatch(s)) return 'tracking.err.awb_format';
  final serial = int.parse(s.substring(3, 10));
  if (serial % 7 != int.parse(s[10])) return 'tracking.err.awb_check';
  return null;
}

/// IMO number: 7 digits; sum of first six digits weighted 7..2, last digit of sum = check digit.
String? validateImo(String input) {
  var s = normalizeReference(input);
  if (s.startsWith('IMO')) s = s.substring(3);
  if (!RegExp(r'^[0-9]{7}$').hasMatch(s)) return 'tracking.err.imo_format';
  var sum = 0;
  for (var i = 0; i < 6; i++) {
    sum += int.parse(s[i]) * (7 - i);
  }
  if (sum % 10 != int.parse(s[6])) return 'tracking.err.imo_check';
  return null;
}

String? validateBl(String input) {
  final s = normalizeReference(input);
  if (!RegExp(r'^[A-Z0-9]{6,25}$').hasMatch(s)) return 'tracking.err.bl_format';
  return null;
}

String? validateReference(ReferenceType type, String input) {
  if (input.trim().isEmpty) return 'tracking.err.empty';
  switch (type) {
    case ReferenceType.container:
      return validateContainer(input);
    case ReferenceType.awb:
      return validateAwb(input);
    case ReferenceType.vesselImo:
      return validateImo(input);
    case ReferenceType.bl:
      return validateBl(input);
  }
}
