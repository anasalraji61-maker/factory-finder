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
