import 'package:factory_finder/core/api/api_client.dart';

/// Notification preferences (GET/PUT /v1/notification-prefs).
/// Pure Dart: parsing, validation and time helpers are unit-testable.

const List<String> kChannels = ['in_app', 'push', 'email'];

/// Alert types from contracts/openapi/notifications.yaml (Alert.rule).
const List<String> kAlertTypes = [
  'price_drop',
  'below_target',
  'cheaper_equivalent',
  'back_in_stock',
  'new_results',
];

const String kDefaultTimezone = 'Asia/Baghdad';

const List<String> kTimezones = [
  'Asia/Baghdad',
  'Asia/Dubai',
  'Asia/Riyadh',
  'Europe/Istanbul',
  'Europe/London',
  'Asia/Shanghai',
  'America/New_York',
  'UTC',
];

class NotifyPrefs {
  const NotifyPrefs({
    this.channels = const <String, Set<String>>{},
    this.quietStart,
    this.quietEnd,
    this.timezone = kDefaultTimezone,
    this.language,
    this.email,
    this.digestEmailVerified = false,
    this.digestEmailPending,
  });

  final Map<String, Set<String>> channels;

  /// "HH:mm" or null (no quiet hours). Both are set together.
  final String? quietStart;
  final String? quietEnd;
  final String timezone;
  final String? language; // 'ar' | 'en' | null

  /// VERIFIED digest address (null when none).
  final String? email;
  final bool digestEmailVerified;

  /// Masked address awaiting its 6-digit code (null when none).
  final String? digestEmailPending;

  bool get hasQuietHours => quietStart != null && quietEnd != null;

  bool isOn(String alertType, String channel) =>
      channels[alertType]?.contains(channel) ?? (channel == 'in_app');

  NotifyPrefs withChannel(String alertType, String channel, bool on) {
    final next = <String, Set<String>>{
      for (final e in channels.entries) e.key: {...e.value},
    };
    final set = next.putIfAbsent(alertType, () => {'in_app'});
    if (on) {
      set.add(channel);
    } else {
      set.remove(channel);
    }
    return copyWith(channels: next);
  }

  NotifyPrefs copyWith({
    Map<String, Set<String>>? channels,
    String? quietStart,
    String? quietEnd,
    bool clearQuiet = false,
    String? timezone,
    String? language,
    String? email,
    bool? digestEmailVerified,
    String? digestEmailPending,
    bool clearPending = false,
  }) =>
      NotifyPrefs(
        channels: channels ?? this.channels,
        quietStart: clearQuiet ? null : (quietStart ?? this.quietStart),
        quietEnd: clearQuiet ? null : (quietEnd ?? this.quietEnd),
        timezone: timezone ?? this.timezone,
        language: language ?? this.language,
        email: email ?? this.email,
        digestEmailVerified: digestEmailVerified ?? this.digestEmailVerified,
        digestEmailPending:
            clearPending ? null : (digestEmailPending ?? this.digestEmailPending),
      );

  factory NotifyPrefs.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    final channels = <String, Set<String>>{};
    final rawCh = m['channels'];
    if (rawCh is Map) {
      rawCh.forEach((k, v) {
        if (v is List) {
          channels[k.toString()] =
              v.map((e) => e.toString()).where(kChannels.contains).toSet();
        }
      });
    }
    String? start;
    String? end;
    final q = m['quiet_hours'];
    if (q is Map) {
      final s = q['start']?.toString();
      final e = q['end']?.toString();
      if (parseHhmm(s) != null && parseHhmm(e) != null) {
        start = s;
        end = e;
      }
    }
    final tz = m['timezone'];
    final lang = m['language'];
    final rawEmail = m['digest_email'] ?? m['email'];
    final email = rawEmail is String && rawEmail.isNotEmpty ? rawEmail : null;
    final rawVerified = m['digest_email_verified'];
    final rawPending = m['digest_email_pending'];
    return NotifyPrefs(
      channels: channels,
      quietStart: start,
      quietEnd: end,
      timezone: (tz is String && tz.isNotEmpty) ? tz : kDefaultTimezone,
      language: (lang == 'ar' || lang == 'en') ? lang as String : null,
      email: email,
      // Legacy responses have no flag: a present address counts as verified.
      digestEmailVerified: rawVerified is bool ? rawVerified : email != null,
      digestEmailPending:
          (rawPending is String && rawPending.isNotEmpty) ? rawPending : null,
    );
  }

  /// Body for PUT /v1/notification-prefs (NotificationPrefsUpdate).
  /// [digestEmail] is sent only when non-null; '' clears the digest address.
  Map<String, dynamic> toUpdateJson({String? digestEmail}) => {
        'channels': {
          for (final e in channels.entries)
            e.key: (e.value.toList()..sort()),
        },
        if (hasQuietHours)
          'quiet_hours': {'start': quietStart, 'end': quietEnd}
        else
          'clear_quiet_hours': true,
        'timezone': timezone,
        if (language != null) 'language': language,
        if (digestEmail != null) 'digest_email': digestEmail.trim(),
      };
}

/// Parses "HH:mm" into (hour, minute), or null when malformed.
({int hour, int minute})? parseHhmm(String? s) {
  if (s == null) return null;
  final m = RegExp(r'^(\d{1,2}):(\d{2})$').firstMatch(s.trim());
  if (m == null) return null;
  final h = int.parse(m.group(1)!);
  final min = int.parse(m.group(2)!);
  if (h > 23 || min > 59) return null;
  return (hour: h, minute: min);
}

String formatHhmm(int hour, int minute) =>
    '${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}';

/// i18n key of the problem with the digest email, or null when OK/empty.
String? validateDigestEmail(String? value) {
  final v = (value ?? '').trim();
  if (v.isEmpty) return null;
  final ok = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$').hasMatch(v);
  return ok ? null : 'notifyprefs.err_email';
}

enum DigestEmailState { none, verified, pending }

/// Maps a prefs response to the digest e-mail UI state (pending wins).
DigestEmailState digestEmailState(NotifyPrefs p) {
  if (p.digestEmailPending != null) return DigestEmailState.pending;
  if (p.email != null && p.digestEmailVerified) return DigestEmailState.verified;
  return DigestEmailState.none;
}

/// What to send as `digest_email` on save: null = leave untouched,
/// '' = clear, otherwise the new address. [baseline] is the field's text when
/// loaded (the verified address or '').
String? digestEmailToSend({required String input, required String baseline}) {
  final t = input.trim();
  return t == baseline.trim() ? null : t;
}

const int kResendCooldownSeconds = 60;

/// Seconds left before the code may be re-sent (0 = allowed now).
int resendCooldownRemaining(DateTime? lastSent, DateTime now,
    {int cooldownSeconds = kResendCooldownSeconds}) {
  if (lastSent == null) return 0;
  final left = cooldownSeconds - now.difference(lastSent).inSeconds;
  return left > 0 ? left : 0;
}

bool isValidVerificationCode(String s) => RegExp(r'^\d{6}$').hasMatch(s.trim());

/// Masks an address like the server does: a***@e***.com.
String maskEmail(String email) {
  final at = email.indexOf('@');
  if (at <= 0) return '***';
  final local = email.substring(0, at);
  final domain = email.substring(at + 1);
  final dot = domain.lastIndexOf('.');
  final host = dot > 0 ? domain.substring(0, dot) : domain;
  final tld = dot > 0 ? domain.substring(dot) : '';
  final h = host.isEmpty ? '' : host.substring(0, 1);
  return '${local.substring(0, 1)}***@$h***$tld';
}

/// i18n key for a failed verify / resend / digest-email save.
String digestEmailErrorKey(Object error) {
  if (error is ApiException) {
    switch (error.code) {
      case 'invalid_code':
        return 'notifyprefs.err.invalid_code';
      case 'code_expired':
        return 'notifyprefs.err.code_expired';
      case 'no_pending':
        return 'notifyprefs.err.no_pending';
      case 'locked':
        return 'notifyprefs.err.locked';
      case 'send_limit':
        return 'notifyprefs.err.send_limit';
      case 'email_disabled':
        return 'notifyprefs.err.email_disabled';
    }
    if (error.status == 429) return 'notifyprefs.err.send_limit';
  }
  return 'notifyprefs.err.generic';
}
