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
    final id = 'mock${_seq.toString().padLeft(28, '0')}';
    return UploadedImage(
      id: id,
      url: '/v1/media/files/$id.jpg',
      width: 800,
      height: 600,
      bytes: image.bytes.length,
      contentType: image.mime,
    );
  }
}

final mediaRepositoryProvider = Provider<MediaRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockMediaRepository() : LiveMediaRepository(api);
});
