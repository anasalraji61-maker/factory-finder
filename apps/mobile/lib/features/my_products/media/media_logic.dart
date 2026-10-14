import 'package:factory_finder/core/api/api_client.dart';

/// Pure helpers for image upload (no Flutter, no plugins).

const int kMaxImageBytes = 5 * 1024 * 1024;
const List<String> kAllowedImageMimes = <String>[
  'image/jpeg',
  'image/png',
  'image/webp',
];

/// Mime from [declared] when allowed, else guessed from the file extension.
/// Returns '' when unknown.
String inferImageMime(String filename, String? declared) {
  final d = (declared ?? '').toLowerCase().trim();
  if (d == 'image/jpg') return 'image/jpeg';
  if (kAllowedImageMimes.contains(d)) return d;
  final n = filename.toLowerCase();
  if (n.endsWith('.jpg') || n.endsWith('.jpeg')) return 'image/jpeg';
  if (n.endsWith('.png')) return 'image/png';
  if (n.endsWith('.webp')) return 'image/webp';
  return d;
}

/// i18n key of the problem with a picked file, or null when it can be uploaded.
String? checkImageFile({required int bytes, required String mime}) {
  if (bytes <= 0) return 'myp.media.err.empty';
  if (!kAllowedImageMimes.contains(mime)) return 'myp.media.err.type';
  if (bytes > kMaxImageBytes) return 'myp.media.err.too_large';
  return null;
}

/// Makes a server-relative media URL absolute against [baseUrl].
String resolveMediaUrl(String baseUrl, String url) {
  final u = url.trim();
  if (u.startsWith('http://') || u.startsWith('https://')) return u;
  final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
  return u.startsWith('/') ? '$base$u' : '$base/$u';
}

/// 200px-wide thumbnail for our own media files; other URLs are returned as is.
String mediaThumbUrl(String baseUrl, String url, {int width = 200}) {
  final full = resolveMediaUrl(baseUrl, url);
  if (!full.contains('/v1/media/files/') || full.contains('?')) return full;
  return '$full?w=$width';
}

/// 32-hex media id inside a media reference (`/v1/media/private/<id>.jpg`,
/// `/v1/media/files/<id>.png`, absolute or not); null when there is none.
String? mediaIdFromRef(String ref) {
  final m = RegExp(r'([a-f0-9]{32})\.(?:jpg|png|webp)(?:$|[?#])').firstMatch(ref);
  return m?.group(1);
}

/// Returns a copy of [list] with the item at [index] moved by [delta]
/// (-1 = earlier, +1 = later). Out-of-range moves return an unchanged copy.
List<T> moveItem<T>(List<T> list, int index, int delta) {
  final out = List<T>.of(list);
  final to = index + delta;
  if (index < 0 || index >= out.length || to < 0 || to >= out.length) return out;
  final item = out.removeAt(index);
  out.insert(to, item);
  return out;
}

/// i18n key for a failed upload.
String mediaErrorKey(Object error) {
  if (error is ApiException) {
    switch (error.status) {
      case 401:
        return 'myp.media.err.auth';
      case 413:
        return 'myp.media.err.too_large';
      case 415:
        return 'myp.media.err.type';
      case 422:
        return 'myp.media.err.corrupt';
      case 429:
        return error.retryAfterSeconds != null
            ? 'myp.media.err.quota_wait'
            : 'myp.media.err.quota';
    }
    if (error.code == 'timeout' || error.code == 'network_error') {
      return 'myp.err.network';
    }
  }
  return 'myp.media.err.generic';
}
