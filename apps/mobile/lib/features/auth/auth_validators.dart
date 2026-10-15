import 'dart:convert';

/// bcrypt ignores everything past 72 bytes; the gateway rejects longer
/// passwords (422), so the client checks the UTF-8 byte length first.
const int kMaxPasswordBytes = 72;

/// True when [password] is longer than [kMaxPasswordBytes] in UTF-8 (Arabic
/// letters take 2 bytes each, emoji 4, so character count is not enough).
bool passwordTooLong(String password) =>
    utf8.encode(password).length > kMaxPasswordBytes;

/// Returns an i18n key for the error or null when valid.
String? validateEmail(String? v) {
  final t = (v ?? '').trim();
  if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(t)) return 'auth.err.email';
  return null;
}

String? validatePassword(String? v) {
  if ((v ?? '').length < 8) return 'auth.err.password';
  if (passwordTooLong(v!)) return 'auth.err.password_long';
  return null;
}

String? validateName(String? v) {
  if ((v ?? '').trim().isEmpty) return 'auth.err.name';
  return null;
}

/// Minimum length of a new password (same policy hint as registration).
const int kMinPasswordLength = 8;

/// New password: at least [kMinPasswordLength] characters and, when
/// [current] is given and non-empty, different from it.
String? validateNewPassword(String? v, {String? current}) {
  final t = v ?? '';
  if (t.length < kMinPasswordLength) return 'auth.err.password';
  if (passwordTooLong(t)) return 'auth.err.password_long';
  if (current != null && current.isNotEmpty && t == current) {
    return 'auth.err.password_same';
  }
  return null;
}

String? validatePasswordConfirm(String? v, String? password) {
  if ((v ?? '') != (password ?? '')) return 'auth.err.password_mismatch';
  return null;
}

String? validateCurrentPassword(String? v) {
  if ((v ?? '').isEmpty) return 'auth.err.current_password';
  return null;
}

/// Reset token pasted from the email. Tolerates surrounding whitespace.
String? validateResetToken(String? v) {
  if ((v ?? '').trim().isEmpty) return 'auth.err.token';
  return null;
}

/// Replaces Arabic-Indic (U+0660..0669) and Eastern Arabic-Indic / Persian
/// (U+06F0..06F9) digits with ASCII digits.
String normalizeDigits(String input) {
  final b = StringBuffer();
  for (final r in input.runes) {
    if (r >= 0x0660 && r <= 0x0669) {
      b.writeCharCode(0x30 + r - 0x0660);
    } else if (r >= 0x06F0 && r <= 0x06F9) {
      b.writeCharCode(0x30 + r - 0x06F0);
    } else {
      b.writeCharCode(r);
    }
  }
  return b.toString();
}

/// Normalizes a phone number to E.164 (`+9647701234567`), or null when it is
/// empty or not a valid number. Accepts Arabic-Indic digits, spaces, dashes,
/// dots and parentheses, `00` / `+` international prefixes, a bare `964...`,
/// and the Iraqi local form `07xx xxx xxxx`. Iraqi (+964) numbers need a
/// 9-10 digit national part; other countries must be given with `+`/`00`.
String? normalizePhone(String? v) {
  var t = normalizeDigits((v ?? '').trim()).replaceAll(RegExp(r'[\s\-.()\u200E\u200F]'), '');
  if (t.isEmpty) return null;
  if (t.startsWith('00')) {
    t = '+${t.substring(2)}';
  } else if (t.startsWith('964')) {
    t = '+$t';
  } else if (t.startsWith('0') && !t.startsWith('00')) {
    t = '+964${t.substring(1)}';
  }
  if (!RegExp(r'^\+[1-9]\d{7,14}$').hasMatch(t)) return null;
  if (t.startsWith('+964') && !RegExp(r'^\+964[1-9]\d{8,9}$').hasMatch(t)) return null;
  return t;
}

/// Phone is optional: empty is valid. Otherwise it must normalize.
String? validatePhone(String? v) {
  if ((v ?? '').trim().isEmpty) return null;
  return normalizePhone(v) == null ? 'auth.err.phone' : null;
}
