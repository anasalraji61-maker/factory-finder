class UploadedImage {
  const UploadedImage({
    required this.id,
    required this.url,
    this.width,
    this.height,
    this.bytes,
    this.contentType,
  });

  final String id;

  /// May be server-relative (`/v1/media/files/..`).
  final String url;
  final int? width;
  final int? height;
  final int? bytes;
  final String? contentType;

  factory UploadedImage.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    int? asInt(Object? v) => v is num ? v.toInt() : null;
    return UploadedImage(
      id: (m['id'] ?? '').toString(),
      url: (m['url'] ?? '').toString(),
      width: asInt(m['width']),
      height: asInt(m['height']),
      bytes: asInt(m['bytes']),
      contentType: m['content_type']?.toString(),
    );
  }
}

/// Result of POST /v1/media/files/{id}/sign (short-lived private-file URL).
class SignedUrl {
  const SignedUrl({required this.url, required this.ttlSeconds});

  final String url;
  final int ttlSeconds;

  factory SignedUrl.fromJson(Object? json) {
    final m = json is Map ? json : const <String, dynamic>{};
    final ttl = m['ttl_seconds'];
    return SignedUrl(
      url: (m['url'] ?? '').toString(),
      ttlSeconds: ttl is num ? ttl.toInt() : 0,
    );
  }
}
