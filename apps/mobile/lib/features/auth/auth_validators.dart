/// Returns an i18n key for the error or null when valid.
String? validateEmail(String? v) {
  final t = (v ?? '').trim();
  if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(t)) return 'auth.err.email';
  return null;
}

String? validatePassword(String? v) {
  if ((v ?? '').length < 8) return 'auth.err.password';
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
