import 'dart:typed_data';

import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

class PickedImage {
  const PickedImage({required this.bytes, required this.filename, required this.mime});

  final Uint8List bytes;
  final String filename;
  final String mime;
}

/// Hides the image_picker plugin so tests never touch it.
/// Both methods return null when the user cancels.
abstract class ImagePickService {
  Future<PickedImage?> pickFromGallery();
  Future<PickedImage?> pickFromCamera();

  /// Android only: a pick result lost because the OS killed the app while the
  /// camera/gallery was open. Null when there is none (and on other platforms).
  Future<PickedImage?> retrieveLost();
}

class PluginImagePickService implements ImagePickService {
  PluginImagePickService([ImagePicker? picker]) : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  Future<PickedImage?> _pick(ImageSource source) async {
    final file = await _picker.pickImage(
      source: source,
      // Phone cameras produce 8-15 MB files that exceed the upload limit and
      // blow up memory; downscale at the source.
      maxWidth: 2048,
      maxHeight: 2048,
      imageQuality: 85,
    );
    if (file == null) return null;
    return _toPicked(file);
  }

  Future<PickedImage> _toPicked(XFile file) async {
    final bytes = await file.readAsBytes();
    final name = file.name.isEmpty ? 'photo.jpg' : file.name;
    return PickedImage(
      bytes: bytes,
      filename: name,
      mime: inferImageMime(name, file.mimeType),
    );
  }

  @override
  Future<PickedImage?> retrieveLost() async {
    try {
      final r = await _picker.retrieveLostData();
      if (r.isEmpty || r.file == null) return null;
      return _toPicked(r.file!);
    } catch (_) {
      return null; // unsupported platform / plugin error
    }
  }

  @override
  Future<PickedImage?> pickFromGallery() => _pick(ImageSource.gallery);

  @override
  Future<PickedImage?> pickFromCamera() => _pick(ImageSource.camera);
}

/// Test fake: returns [next] (or null) without any plugin.
class FakeImagePickService implements ImagePickService {
  FakeImagePickService({this.next});

  PickedImage? next;

  /// Returned once by [retrieveLost], then cleared.
  PickedImage? lost;
  int galleryCalls = 0;
  int cameraCalls = 0;

  @override
  Future<PickedImage?> retrieveLost() async {
    final l = lost;
    lost = null;
    return l;
  }

  @override
  Future<PickedImage?> pickFromGallery() async {
    galleryCalls++;
    return next;
  }

  @override
  Future<PickedImage?> pickFromCamera() async {
    cameraCalls++;
    return next;
  }
}

final imagePickServiceProvider =
    Provider<ImagePickService>((ref) => PluginImagePickService());
