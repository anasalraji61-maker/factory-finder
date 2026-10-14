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
