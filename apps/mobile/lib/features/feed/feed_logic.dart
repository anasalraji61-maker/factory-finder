import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/feed/feed_models.dart';

/// Pure helpers: client-side content checks (mirroring the server's
/// `content_rejected` screening for contact details), tag handling and the
/// mapping of every feed error code to an i18n key.

enum ContactKind { url, email, phone, handle }

const String _arDigits = '٠١٢٣٤٥٦٧٨٩';
const String _faDigits = '۰۱۲۳۴۵۶۷۸۹';

String _asciiDigits(String s) {
  final b = StringBuffer();
  for (final r in s.runes) {
    final c = String.fromCharCode(r);
    var i = _arDigits.indexOf(c);
    if (i < 0) i = _faDigits.indexOf(c);
    b.write(i >= 0 ? '$i' : c);
  }
  return b.toString();
}

const String _tlds =
    'com|net|org|info|biz|io|co|me|ly|cc|top|xyz|shop|store|site|online|app|link|ru|tk|cn|iq|ae|sa|tr|uk|ir|eg';

final RegExp _urlRe = RegExp(
  r'(?:https?://|ftp://|www\.)\S+|(?<![\w.@-])(?:[a-z0-9-]+\.)+(?:' +
      _tlds +
      r')(?![\w-])|\bdot\s*com\b|نقطة\s*كوم',
  caseSensitive: false,
);
final RegExp _emailRe = RegExp(
  r'[\w.+-]+\s*(?:@|\[at\]|\(at\))\s*[\w-]+(?:\s*(?:\.|\[dot\]|\(dot\))\s*[\w-]+)+',
  caseSensitive: false,
);
final RegExp _phoneRe = RegExp(r'(?<![\w.])\+?\(?\d[\d\s\-().]{6,}\d(?!\w)');
final RegExp _handleRe = RegExp(
  r'(?<![\w@])@[a-z0-9_.]{3,}|'
  r'\b(?:whats\s*app|wechat|weixin|telegram|viber|skype|snapchat|signal\s+app|line\s+id|imo)\b|'
  r'واتس\s*اب|واتساب|وتساب|تلكرام|تليجرام|تيليجرام|فايبر|سناب\s*شات|سناب|ويشات|微信',
  caseSensitive: false,
);

/// First kind of contact detail found in [text] (server codes
/// contact_url / contact_email / contact_phone / contact_handle), or null.
ContactKind? findContactDetail(String text) {
  final t = _asciiDigits(text);
  if (_urlRe.hasMatch(t)) return ContactKind.url;
  if (_emailRe.hasMatch(t)) return ContactKind.email;
  for (final m in _phoneRe.allMatches(t)) {
    final digits = m.group(0)!.replaceAll(RegExp(r'\D'), '').length;
    if (digits >= 9) return ContactKind.phone;
  }
  if (_handleRe.hasMatch(t)) return ContactKind.handle;
  return null;
}

String _contactKey(ContactKind k) => 'feed.err.contact.${k.name}';

/// i18n key of the first problem with a post body, or null when it can be sent.
String? validatePostBody(String body) {
  final t = body.trim();
  if (t.isEmpty) return 'feed.err.body_empty';
  if (t.runes.length > kPostBodyMax) return 'feed.err.post_too_long';
  if (_hasControl(t)) return 'feed.err.control_chars';
  final k = findContactDetail(t);
  return k == null ? null : _contactKey(k);
}

/// i18n key of the first problem with a comment, or null.
String? validateCommentBody(String body) {
  final t = body.trim();
  if (t.isEmpty) return 'feed.err.body_empty';
  if (t.runes.length > kCommentBodyMax) return 'feed.err.comment_too_long';
  if (_hasControl(t)) return 'feed.err.control_chars';
  final k = findContactDetail(t);
  return k == null ? null : _contactKey(k);
}

/// Tags are screened by the server too.
String? validateTags(List<String> tags) {
  for (final t in tags) {
    final k = findContactDetail(t);
    if (k != null) return _contactKey(k);
  }
  return null;
}

/// Report details are stored redacted, but contact details are still rejected
/// client-side to keep the UX consistent.
String? validateReportDetails(String details) {
  if (details.trim().runes.length > kReportDetailsMax) return 'feed.err.details_too_long';
  return null;
}

bool _hasControl(String s) {
  for (final r in s.runes) {
    // Newlines and tabs are fine in a post; other control chars are rejected.
    if (r == 0x0A || r == 0x0D || r == 0x09) continue;
    if (r < 0x20 || (r >= 0x7F && r < 0xA0)) return true;
  }
  return false;
}

final RegExp _tagRe = RegExp(r'^[\p{L}\p{N}_-]{1,30}$', unicode: true);

/// Splits free text on whitespace / commas / `#`, lower-cases, drops invalid
/// ones and duplicates, keeps at most [kPostTagsMax].
List<String> parseTags(String raw) {
  final out = <String>[];
  for (final part in raw.split(RegExp(r'[\s,#،;]+'))) {
    final t = part.trim().toLowerCase();
    if (t.isEmpty || !_tagRe.hasMatch(t) || out.contains(t)) continue;
    out.add(t);
    if (out.length >= kPostTagsMax) break;
  }
  return out;
}

/// Tag tokens in [raw] that cannot be used (too long / illegal characters).
bool hasInvalidTags(String raw) {
  for (final part in raw.split(RegExp(r'[\s,#،;]+'))) {
    final t = part.trim().toLowerCase();
    if (t.isNotEmpty && !_tagRe.hasMatch(t)) return true;
  }
  return false;
}

/// True when [raw] holds more valid, distinct tags than a post may carry
/// (parseTags would silently drop the rest).
bool hasTooManyTags(String raw) {
  final seen = <String>{};
  for (final part in raw.split(RegExp(r'[\s,#،;]+'))) {
    final t = part.trim().toLowerCase();
    if (t.isNotEmpty && _tagRe.hasMatch(t)) seen.add(t);
  }
  return seen.length > kPostTagsMax;
}

/// Upper-case initials (max 2 letters) of a supplier name for the avatar.
String initialsOf(String name) {
  final words = name.trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  if (words.isEmpty) return '?';
  String first(String w) => String.fromCharCode(w.runes.first).toUpperCase();
  if (words.length == 1) return first(words.first);
  return first(words[0]) + first(words[1]);
}

/// i18n key plus arguments for a feed failure.
class FeedErrorText {
  const FeedErrorText(this.key, [this.args = const <String, String>{}]);

  final String key;
  final Map<String, String> args;
}

/// Maps every documented feed error code (and 401/429/network) to a message.
FeedErrorText describeFeedError(Object e) {
  if (e is! ApiException) return const FeedErrorText('feed.err.generic');
  switch (e.code) {
    case 'rate_limited':
      return _rateLimited(e.retryAfterSeconds);
    case 'content_rejected':
      return const FeedErrorText('feed.err.content_rejected');
    case 'invalid_media':
      return const FeedErrorText('feed.err.invalid_media');
    case 'invalid_cursor':
      return const FeedErrorText('feed.err.invalid_cursor');
    case 'supplier_required':
      return const FeedErrorText('feed.err.supplier_required');
    case 'post_limit_reached':
      return const FeedErrorText('feed.err.post_limit');
    case 'follow_limit_reached':
      return const FeedErrorText('feed.err.follow_limit');
    case 'comment_limit_reached':
      return const FeedErrorText('feed.err.comment_limit');
    case 'cannot_follow_self':
      return const FeedErrorText('feed.err.follow_self');
    case 'cannot_mute_self':
      return const FeedErrorText('feed.err.mute_self');
    case 'cannot_report_own':
      return const FeedErrorText('feed.err.report_own');
    case 'not_found':
      return const FeedErrorText('feed.err.not_found');
    case 'unauthenticated':
      return const FeedErrorText('feed.err.auth');
    case 'forbidden':
      return const FeedErrorText('feed.err.forbidden');
    case 'validation_error':
      return const FeedErrorText('feed.err.validation');
    case 'timeout':
    case 'network_error':
      return const FeedErrorText('feed.err.network');
  }
  switch (e.status) {
    case 401:
      return const FeedErrorText('feed.err.auth');
    case 403:
      return const FeedErrorText('feed.err.forbidden');
    case 404:
      return const FeedErrorText('feed.err.not_found');
    case 429:
      return _rateLimited(e.retryAfterSeconds);
    case 422:
      return const FeedErrorText('feed.err.validation');
  }
  return const FeedErrorText('feed.err.generic');
}

FeedErrorText _rateLimited(int? seconds) {
  if (seconds == null || seconds <= 0) return const FeedErrorText('feed.err.rate_limited');
  if (seconds < 60) {
    return FeedErrorText('feed.err.rate_limited_s', {'n': '$seconds'});
  }
  return FeedErrorText('feed.err.rate_limited_m', {'n': '${(seconds / 60).ceil()}'});
}

/// Absolute URL for a post image; our own files get a width hint.
String postImageUrl(String baseUrl, String url, {int? width}) {
  final u = url.trim();
  final abs = (u.startsWith('http://') || u.startsWith('https://'))
      ? u
      : '${baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl}'
          '${u.startsWith('/') ? '' : '/'}$u';
  if (width == null || !abs.contains('/v1/media/files/') || abs.contains('?')) return abs;
  return '$abs?w=$width';
}
