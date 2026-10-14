import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/widgets/feed_common.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Post composer. Only a verified supplier can publish (the server enforces
/// it too: 403 `supplier_required`).
class ComposerScreen extends ConsumerStatefulWidget {
  const ComposerScreen({super.key});

  @override
  ConsumerState<ComposerScreen> createState() => _ComposerScreenState();
}

class _ComposerScreenState extends ConsumerState<ComposerScreen> {
  final TextEditingController _body = TextEditingController();
  final TextEditingController _tags = TextEditingController();

  /// Server-relative media URLs (`/v1/media/files/..`) as returned by upload.
  final List<String> _media = <String>[];
  int _uploading = 0;
  String? _listingRef;
  String? _listingTitle;
  String? _bodyError;
  String? _tagsError;
  String? _submitError;
  bool _busy = false;

  @override
  void dispose() {
    _body.dispose();
    _tags.dispose();
    super.dispose();
  }

  Future<void> _addImage(bool camera) async {
    if (_media.length + _uploading >= kPostMediaMax) {
      showFeedSnack(context, context.tr('feed.err.image_limit'));
      return;
    }
    final picker = ref.read(imagePickServiceProvider);
    PickedImage? picked;
    try {
      picked = camera ? await picker.pickFromCamera() : await picker.pickFromGallery();
    } catch (_) {
      if (mounted) showFeedSnack(context, context.tr('myp.media.err.generic'));
      return;
    }
    if (picked == null || !mounted) return;
    final problem = checkImageFile(bytes: picked.bytes.length, mime: picked.mime);
    if (problem != null) {
      showFeedSnack(context, context.tr(problem));
      return;
    }
    setState(() => _uploading++);
    try {
      final up = await ref.read(mediaRepositoryProvider).uploadImage(picked);
      if (!mounted) return;
      setState(() {
        _uploading--;
        if (_media.length < kPostMediaMax) _media.add(up.url);
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _uploading--);
      showFeedSnack(context, context.tr(mediaErrorKey(e)));
    }
  }

  Future<void> _pickListing() async {
    final picked = await showModalBottomSheet<OwnedListing>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const _ListingPickerSheet(),
    );
    if (picked == null || !mounted) return;
    setState(() {
      _listingRef = picked.id;
      _listingTitle = picked.title;
    });
  }

  bool _validate() {
    final bodyProblem = validatePostBody(_body.text);
    String? tagsProblem;
    if (hasInvalidTags(_tags.text)) {
      tagsProblem = 'feed.err.tag_invalid';
    } else {
      final tags = parseTags(_tags.text);
      tagsProblem = validateTags(tags);
    }
    setState(() {
      _bodyError = bodyProblem == null ? null : context.tr(bodyProblem);
      _tagsError = tagsProblem == null ? null : context.tr(tagsProblem);
      _submitError = null;
    });
    return bodyProblem == null && tagsProblem == null;
  }

  Future<void> _publish() async {
    if (_busy || _uploading > 0 || !_validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(feedActionsProvider).publish(
            PostDraft(
              body: _body.text,
              media: List<String>.of(_media),
              tags: parseTags(_tags.text),
              listingRef: _listingRef,
            ),
          );
      if (!mounted) return;
      showFeedSnack(context, context.tr('feed.published'));
      if (context.canPop()) {
        context.pop();
      } else {
        context.go('/feed');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _submitError = feedErrorMessage(context, e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final theme = Theme.of(context);
    final base = ref.watch(apiClientProvider).baseUrl;

    Widget gate(String titleKey, String msgKey, String actionKey, String route) => EmptyState(
          icon: Icons.storefront_outlined,
          title: context.tr(titleKey),
          message: context.tr(msgKey),
          action: FilledButton(
            key: const ValueKey<String>('feed-composer-gate-action'),
            onPressed: () => context.push(route),
            child: Text(context.tr(actionKey)),
          ),
        );

    Widget content;
    if (me == null) {
      content = gate('feed.composer.login_title', 'feed.composer.login_msg', 'feed.composer.login_action', '/login');
    } else if (!isVerifiedSupplier(me)) {
      content = gate('feed.composer.supplier_title', 'feed.composer.supplier_msg', 'feed.composer.supplier_action', '/supplier-claim');
    } else {
      content = ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          TextField(
            key: const ValueKey<String>('feed-composer-body'),
            controller: _body,
            enabled: !_busy,
            minLines: 4,
            maxLines: 10,
            maxLength: kPostBodyMax,
            onChanged: (_) {
              if (_bodyError != null) setState(() => _bodyError = null);
            },
            decoration: InputDecoration(
              labelText: context.tr('feed.composer.body'),
              hintText: context.tr('feed.composer.body_hint'),
              errorText: _bodyError,
              errorMaxLines: 3,
              alignLabelWithHint: true,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            key: const ValueKey<String>('feed-composer-tags'),
            controller: _tags,
            enabled: !_busy,
            onChanged: (_) {
              if (_tagsError != null) setState(() => _tagsError = null);
            },
            decoration: InputDecoration(
              labelText: context.tr('feed.composer.tags'),
              helperText: context.tr('feed.composer.tags_hint'),
              helperMaxLines: 2,
              errorText: _tagsError,
              errorMaxLines: 3,
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            context.tr('feed.composer.images', {'n': '${_media.length}', 'max': '$kPostMediaMax'}),
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              for (var i = 0; i < _media.length; i++)
                SizedBox(
                  width: 84,
                  height: 84,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      AppNetworkImage(
                        url: postImageUrl(base, _media[i], width: 200),
                        fit: BoxFit.cover,
                        borderRadius: BorderRadius.circular(AppRadius.sm),
                      ),
                      PositionedDirectional(
                        top: 0,
                        end: 0,
                        child: IconButton(
                          key: ValueKey<String>('feed-composer-remove-$i'),
                          tooltip: context.tr('feed.composer.remove_image'),
                          style: IconButton.styleFrom(
                            backgroundColor: Colors.black54,
                            foregroundColor: Colors.white,
                            minimumSize: const Size(32, 32),
                            padding: EdgeInsets.zero,
                          ),
                          icon: const Icon(Icons.close, size: 18),
                          onPressed: _busy ? null : () => setState(() => _media.removeAt(i)),
                        ),
                      ),
                    ],
                  ),
                ),
              for (var i = 0; i < _uploading; i++)
                const SizedBox(
                  width: 84,
                  height: 84,
                  child: Center(child: CircularProgressIndicator()),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              OutlinedButton.icon(
                key: const ValueKey<String>('feed-composer-gallery'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: _busy ? null : () => _addImage(false),
                icon: const Icon(Icons.photo_library_outlined),
                label: Text(context.tr('feed.composer.gallery')),
              ),
              OutlinedButton.icon(
                key: const ValueKey<String>('feed-composer-camera'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: _busy ? null : () => _addImage(true),
                icon: const Icon(Icons.photo_camera_outlined),
                label: Text(context.tr('feed.composer.camera')),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            context.tr('feed.composer.listing'),
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (_listingRef != null)
                InputChip(
                  key: const ValueKey<String>('feed-composer-listing-chip'),
                  avatar: const Icon(Icons.inventory_2_outlined, size: 18),
                  label: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 220),
                    child: Text(_listingTitle ?? _listingRef!, overflow: TextOverflow.ellipsis),
                  ),
                  onDeleted: () => setState(() {
                    _listingRef = null;
                    _listingTitle = null;
                  }),
                ),
              OutlinedButton.icon(
                key: const ValueKey<String>('feed-composer-pick-listing'),
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                onPressed: _busy ? null : _pickListing,
                icon: const Icon(Icons.add_link),
                label: Text(context.tr('feed.composer.pick_listing')),
              ),
            ],
          ),
          if (_submitError != null)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.lg),
              child: Text(
                _submitError!,
                key: const ValueKey<String>('feed-composer-error'),
                style: TextStyle(color: theme.colorScheme.error),
              ),
            ),
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(
            key: const ValueKey<String>('feed-composer-publish'),
            label: context.tr('feed.composer.publish'),
            icon: Icons.send,
            loading: _busy,
            onPressed: _uploading > 0 ? null : _publish,
          ),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('feed.compose'))),
      body: content,
    );
  }
}

class _ListingPickerSheet extends ConsumerWidget {
  const _ListingPickerSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.7),
        child: FutureBuilder<PageResult<OwnedListing>>(
          future: ref.read(myListingsRepositoryProvider).list(),
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const SizedBox(
                height: 160,
                child: Center(child: CircularProgressIndicator()),
              );
            }
            if (snap.hasError) {
              return ErrorState(error: snap.error, message: feedErrorMessage(context, snap.error!));
            }
            final items = snap.data?.items ?? const <OwnedListing>[];
            if (items.isEmpty) {
              return EmptyState(
                icon: Icons.inventory_2_outlined,
                title: context.tr('feed.composer.no_listings'),
              );
            }
            return ListView.builder(
              shrinkWrap: true,
              itemCount: items.length,
              itemBuilder: (context, i) => ListTile(
                key: ValueKey<String>('feed-pick-${items[i].id}'),
                title: Text(items[i].title, maxLines: 2, overflow: TextOverflow.ellipsis),
                onTap: () => Navigator.of(context).pop(items[i]),
              ),
            );
          },
        ),
      ),
    );
  }
}
