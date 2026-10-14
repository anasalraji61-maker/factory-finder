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
  });

  final Map<String, Set<String>> channels;

  /// "HH:mm" or null (no quiet hours). Both are set together.
  final String? quietStart;
  final String? quietEnd;
  final String timezone;
  final String? language; // 'ar' | 'en' | null
  final String? email;

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
  }) =>
      NotifyPrefs(
        channels: channels ?? this.channels,
        quietStart: clearQuiet ? null : (quietStart ?? this.quietStart),
        quietEnd: clearQuiet ? null : (quietEnd ?? this.quietEnd),
        timezone: timezone ?? this.timezone,
        language: language ?? this.language,
        email: email ?? this.email,
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
    final email = m['email'];
    return NotifyPrefs(
      channels: channels,
      quietStart: start,
      quietEnd: end,
      timezone: (tz is String && tz.isNotEmpty) ? tz : kDefaultTimezone,
      language: (lang == 'ar' || lang == 'en') ? lang as String : null,
      email: (email is String && email.isNotEmpty) ? email : null,
    );
  }

  /// Body for PUT /v1/notification-prefs (NotificationPrefsUpdate).
  Map<String, dynamic> toUpdateJson() => {
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
        if (email != null && email!.trim().isNotEmpty) 'email': email!.trim(),
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
