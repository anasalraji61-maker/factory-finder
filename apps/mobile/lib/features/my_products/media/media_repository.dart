import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class MediaRepository {
  /// Uploads [image]; [onProgress] receives 0..1.
  Future<UploadedImage> uploadImage(
    PickedImage image, {
    String kind = 'listing',
    void Function(double progress)? onProgress,
  });

  /// Owner-only short-lived URL for a private file (404 otherwise).
  Future<SignedUrl> signFile(String id);
}

/// Builds the multipart body of POST /v1/media/images (field `file`, `kind`).
FormData buildImageForm(PickedImage image, String kind) => FormData.fromMap(
      <String, dynamic>{
        'kind': kind,
        'file': MultipartFile.fromBytes(image.bytes, filename: image.filename),
      },
    );

class LiveMediaRepository implements MediaRepository {
  LiveMediaRepository(this._api);
  final ApiClient _api;

  @override
  Future<UploadedImage> uploadImage(
    PickedImage image, {
    String kind = 'listing',
    void Function(double progress)? onProgress,
  }) async {
    final data = await _api.postMultipart(
      '/v1/media/images',
      () => buildImageForm(image, kind),
      onSendProgress: (sent, total) {
        if (onProgress != null && total > 0) onProgress(sent / total);
      },
    );
    return UploadedImage.fromJson(data);
  }

  @override
  Future<SignedUrl> signFile(String id) async => SignedUrl.fromJson(
        await _api.post('/v1/media/files/${Uri.encodeComponent(id)}/sign'),
      );
}

class MockMediaRepository implements MediaRepository {
  int _seq = 0;

  @override
  Future<UploadedImage> uploadImage(
    PickedImage image, {
    String kind = 'listing',
    void Function(double progress)? onProgress,
  }) async {
    await mockDelay(150);
    onProgress?.call(1);
    _seq++;
    final id = _seq.toRadixString(16).padLeft(32, '0');
    // Contract: kind=verification is always private.
    final private = kind == 'verification';
    return UploadedImage(
      id: id,
      url: private ? '/v1/media/private/$id.jpg' : '/v1/media/files/$id.jpg',
      width: 800,
      height: 600,
      bytes: image.bytes.length,
      contentType: image.mime,
    );
  }

  /// Number of sign calls (tests).
  int signCalls = 0;
  Object? signError;

  @override
  Future<SignedUrl> signFile(String id) async {
    signCalls++;
    final err = signError;
    if (err != null) throw err;
    return SignedUrl(
      url: '/v1/media/private/$id.jpg?u=mock&exp=4102444800&sig=mock',
      ttlSeconds: 300,
    );
  }
}

final mediaRepositoryProvider = Provider<MediaRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockMediaRepository() : LiveMediaRepository(api);
});
