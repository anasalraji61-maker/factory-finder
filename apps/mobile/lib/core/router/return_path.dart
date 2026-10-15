const Set<String> _authPaths = <String>{'/login', '/register', '/onboarding'};

/// Returns [raw] only when it is a safe in-app return path, else null.
/// Open-redirect guard: must start with a single '/', no scheme or authority,
/// no backslashes / control characters / whitespace (browsers and some
/// parsers treat '/\\host' like '//host'), also after one round of
/// percent-decoding, and must not point back at an auth screen (loop).
String? sanitizeReturnPath(String? raw) {
  if (raw == null || raw.isEmpty || raw.length > 2048) return null;
  if (!raw.startsWith('/') || raw.startsWith('//')) return null;
  if (RegExp(r'[\\\s\x00-\x1f\x7f]').hasMatch(raw)) return null;
  final uri = Uri.tryParse(raw);
  if (uri == null || uri.hasScheme || uri.hasAuthority) return null;
  String decoded;
  try {
    decoded = Uri.decodeComponent(uri.path);
  } catch (_) {
    return null;
  }
  if (decoded.startsWith('//') ||
      RegExp(r'[\\\s\x00-\x1f\x7f]').hasMatch(decoded)) {
    return null;
  }
  if (_authPaths.contains(uri.path)) return null;
  return raw;
}
