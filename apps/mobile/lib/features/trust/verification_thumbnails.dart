import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Seconds shaved off a signed URL's TTL so a cached URL is never handed out
/// right before it expires.
const int kSignedUrlSafetyMarginSeconds = 30;

/// Fetches signed URLs for private media on demand and caches each for its
/// TTL (minus a safety margin). Failures are never cached; concurrent calls
/// for one id share a single request.
class SignedUrlCache {
  SignedUrlCache(this._repo, {DateTime Function()? now}) : _now = now ?? DateTime.now;

  final MediaRepository _repo;
  final DateTime Function() _now;
  final Map<String, (String, DateTime)> _ok = <String, (String, DateTime)>{};
  final Map<String, Future<String?>> _inflight = <String, Future<String?>>{};

  /// Signed URL (as returned by the server) for the media [id]; null on any failure.
  Future<String?> urlFor(String id) {
    final hit = _ok[id];
    if (hit != null && _now().isBefore(hit.$2)) return Future<String?>.value(hit.$1);
    _ok.remove(id);
    return _inflight[id] ??= _fetch(id).whenComplete(() => _inflight.remove(id));
  }

  Future<String?> _fetch(String id) async {
    try {
      final s = await _repo.signFile(id);
      if (s.url.isEmpty) return null;
      final margin = s.ttlSeconds > 2 * kSignedUrlSafetyMarginSeconds
          ? kSignedUrlSafetyMarginSeconds
          : s.ttlSeconds ~/ 2;
      final life = s.ttlSeconds - margin;
      if (life > 0) _ok[id] = (s.url, _now().add(Duration(seconds: life)));
      return s.url;
    } catch (_) {
      return null;
    }
  }

  /// Drops a cached URL (e.g. the image failed to load with it).
  void forget(String id) => _ok.remove(id);
}

final signedUrlCacheProvider = Provider<SignedUrlCache>(
  (ref) => SignedUrlCache(ref.watch(mediaRepositoryProvider)),
);

/// Thumbnail of one private verification image. Signs on demand, shows a
/// placeholder on any failure (tap to retry).
class VerificationThumb extends ConsumerStatefulWidget {
  const VerificationThumb({super.key, required this.fileRef, required this.index});

  /// Media reference as stored in the document's files[].
  final String fileRef;

  /// 1-based, for the accessibility label.
  final int index;

  @override
  ConsumerState<VerificationThumb> createState() => _VerificationThumbState();
}

class _VerificationThumbState extends ConsumerState<VerificationThumb> {
  static const double _size = 64;
  Future<String?>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(VerificationThumb old) {
    super.didUpdateWidget(old);
    if (old.fileRef != widget.fileRef) _load();
  }

  void _load() {
    final id = mediaIdFromRef(widget.fileRef);
    _future = id == null
        ? Future<String?>.value(null)
        : ref.read(signedUrlCacheProvider).urlFor(id);
  }

  void _retry() {
    final id = mediaIdFromRef(widget.fileRef);
    if (id != null) ref.read(signedUrlCacheProvider).forget(id);
    setState(_load);
  }

  Widget _box(Widget child) => ClipRRect(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        child: SizedBox(width: _size, height: _size, child: child),
      );

  Widget _placeholder(BuildContext context, {bool retry = true}) {
    final box = _box(
      ColoredBox(
        color: AppColors.secondaryOf(context).withOpacity(0.12),
        child: Icon(Icons.image_not_supported_outlined, color: AppColors.secondaryOf(context)),
      ),
    );
    return Semantics(
      label: context.tr('ver.thumb_failed'),
      button: retry,
      child: retry
          ? InkWell(
              key: const ValueKey<String>('ver-thumb-retry'),
              onTap: _retry,
              child: box,
            )
          : box,
    );
  }

  @override
  Widget build(BuildContext context) {
    final base = ref.read(apiClientProvider).baseUrl;
    return FutureBuilder<String?>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return _box(const Center(
            child: SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ));
        }
        final url = snap.data;
        if (url == null) return _placeholder(context);
        return Semantics(
          image: true,
          label: context.tr('ver.thumb_label', {'n': '${widget.index}'}),
          child: _box(
            Image.network(
              resolveMediaUrl(base, url),
              key: const ValueKey<String>('ver-thumb-image'),
              fit: BoxFit.cover,
              gaplessPlayback: true,
              errorBuilder: (context, _, __) => _placeholder(context),
            ),
          ),
        );
      },
    );
  }
}
