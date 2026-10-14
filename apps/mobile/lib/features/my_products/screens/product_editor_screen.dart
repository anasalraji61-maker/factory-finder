import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/logistics/screens/hs_picker.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:factory_finder/features/my_products/moderation_notice.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:factory_finder/features/my_products/screens/my_products_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Create ([listingId] null) or edit a supplier-owned listing.
class ProductEditorScreen extends ConsumerStatefulWidget {
  const ProductEditorScreen({super.key, this.listingId});

  final String? listingId;

  @override
  ConsumerState<ProductEditorScreen> createState() => _ProductEditorScreenState();
}

class _ProductEditorScreenState extends ConsumerState<ProductEditorScreen> {
  final _title = TextEditingController();
  final _titleAr = TextEditingController();
  final _description = TextEditingController();
  final _descriptionAr = TextEditingController();
  final _priceMin = TextEditingController();
  final _priceMax = TextEditingController();
  final _moq = TextEditingController(text: '1');
  final _weight = TextEditingController();
  final _volume = TextEditingController();
  final _hs = TextEditingController();
  final _leadMin = TextEditingController();
  final _leadMax = TextEditingController();
  final _imageInput = TextEditingController();

  ListingKind _kind = ListingKind.product;
  ItemCondition _condition = ItemCondition.brandNew;
  String _category = '';
  String _currency = 'USD';
  String _unit = 'piece';
  Incoterm? _incoterm;
  List<String> _images = <String>[];
  Location _origin = const Location(countryCode: 'IQ');
  Map<String, String> _errors = <String, String>{};
  String? _imageInputError;
  bool _showUrlInput = false;
  final List<_Upload> _uploads = <_Upload>[];
  int _uploadSeq = 0;

  OwnedListing? _existing;
  bool _loading = false;
  String? _loadErrorKey;
  bool _busy = false;

  bool get _isEdit => widget.listingId != null;

  @override
  void initState() {
    super.initState();
    if (_isEdit) {
      _loading = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadExisting();
      });
    }
  }

  @override
  void dispose() {
    for (final c in <TextEditingController>[
      _title, _titleAr, _description, _descriptionAr, _priceMin, _priceMax,
      _moq, _weight, _volume, _hs, _leadMin, _leadMax, _imageInput,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadExisting() async {
    setState(() {
      _loading = true;
      _loadErrorKey = null;
    });
    try {
      final l = await ref.read(myListingsRepositoryProvider).get(widget.listingId!);
      if (!mounted) return;
      final d = l.toDraft();
      setState(() {
        _existing = l;
        _kind = d.kind;
        _condition = d.condition;
        _title.text = d.title;
        _titleAr.text = d.titleAr;
        _description.text = d.description;
        _descriptionAr.text = d.descriptionAr;
        _category = d.category;
        _priceMin.text = d.priceMin;
        _priceMax.text = d.priceMax;
        _currency = kProductCurrencies.contains(d.currency) ? d.currency : kProductCurrencies.first;
        _unit = d.unit;
        _moq.text = d.moq;
        _incoterm = d.incoterm;
        _weight.text = d.unitWeightKg;
        _volume.text = d.unitVolumeM3;
        _hs.text = d.hsCode;
        _leadMin.text = d.leadMin;
        _leadMax.text = d.leadMax;
        _images = d.images;
        _origin = d.origin;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadErrorKey = myProductsErrorKey(e);
      });
    }
  }

  ProductDraft _collect() => ProductDraft(
        kind: _kind,
        condition: _condition,
        title: _title.text,
        titleAr: _titleAr.text,
        description: _description.text,
        descriptionAr: _descriptionAr.text,
        category: _category,
        priceMin: _priceMin.text,
        priceMax: _priceMax.text,
        currency: _currency,
        unit: _unit,
        moq: _moq.text,
        incoterm: _incoterm,
        unitWeightKg: _weight.text,
        unitVolumeM3: _volume.text,
        hsCode: _hs.text,
        leadMin: _leadMin.text,
        leadMax: _leadMax.text,
        images: _images,
        origin: _origin,
      );

  String? _err(String field) {
    final k = _errors[field];
    return k == null ? null : context.tr(k);
  }

  void _clear(String field) {
    if (_errors.containsKey(field)) {
      setState(() => _errors = Map<String, String>.of(_errors)..remove(field));
    }
  }

  /// Validates the form; shows errors and a snackbar when invalid.
  bool _validate() {
    if (_uploads.isNotEmpty) {
      showMyProductsSnack(context, context.tr('myp.media.wait_uploads'));
      return false;
    }
    final errors = validateProductDraft(_collect());
    setState(() => _errors = errors);
    if (errors.isNotEmpty) {
      showMyProductsSnack(context, context.tr('myp.fix_form'));
      return false;
    }
    return true;
  }

  /// Creates or updates; returns the saved listing, or null after showing an error.
  Future<OwnedListing?> _persist() async {
    final repo = ref.read(myListingsRepositoryProvider);
    final draft = _collect();
    try {
      return _isEdit
          ? await repo.update(widget.listingId!, draft)
          : await repo.create(draft);
    } catch (e) {
      if (mounted) showMyProductsSnack(context, context.tr(myProductsErrorKey(e)));
      return null;
    }
  }

  Future<void> _save() async {
    if (_busy || !_validate()) return;
    setState(() => _busy = true);
    final saved = await _persist();
    if (!mounted) return;
    setState(() => _busy = false);
    if (saved == null) return;
    showMyProductsSnack(context, context.tr(_isEdit ? 'myp.ok.updated' : 'myp.ok.created'));
    context.pop(true);
  }

  Future<void> _publish() async {
    if (_busy || !_validate()) return;
    final sure = await confirmMyProductsAction(
      context,
      titleKey: 'myp.confirm.publish_title',
      messageKey: 'myp.confirm.publish_msg',
      confirmKey: 'myp.publish',
    );
    if (!sure || !mounted) return;
    setState(() => _busy = true);
    final saved = await _persist();
    if (saved == null) {
      if (mounted) setState(() => _busy = false);
      return;
    }
    try {
      await ref.read(myListingsRepositoryProvider).publish(saved.id);
      if (!mounted) return;
      setState(() => _busy = false);
      showMyProductsSnack(context, context.tr('myp.ok.published'));
      context.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showMyProductsSnack(context, context.tr(myProductsErrorKey(e)));
    }
  }

  Future<void> _simpleAction({
    required String titleKey,
    required String messageKey,
    required String confirmKey,
    required String okKey,
    required Future<void> Function(MyListingsRepository repo, String id) run,
  }) async {
    if (_busy) return;
    final sure = await confirmMyProductsAction(
      context,
      titleKey: titleKey,
      messageKey: messageKey,
      confirmKey: confirmKey,
    );
    if (!sure || !mounted) return;
    setState(() => _busy = true);
    try {
      await run(ref.read(myListingsRepositoryProvider), widget.listingId!);
      if (!mounted) return;
      setState(() => _busy = false);
      showMyProductsSnack(context, context.tr(okKey));
      context.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      showMyProductsSnack(context, context.tr(myProductsErrorKey(e)));
    }
  }

  void _addImage() {
    final url = _imageInput.text.trim();
    if (url.isEmpty) return;
    if (_images.length >= kMaxProductImages) {
      setState(() => _imageInputError = 'myp.err.image_limit');
      return;
    }
    if (!isValidImageUrl(url)) {
      setState(() => _imageInputError = 'myp.err.image_url');
      return;
    }
    setState(() {
      _images = <String>[..._images, url];
      _imageInput.clear();
      _imageInputError = null;
      _errors = Map<String, String>.of(_errors)..remove('images');
    });
  }

  Future<void> _pickAndUpload(bool camera) async {
    if (_images.length + _uploads.length >= kMaxProductImages) {
      showMyProductsSnack(context, context.tr('myp.err.image_limit'));
      return;
    }
    final picker = ref.read(imagePickServiceProvider);
    PickedImage? picked;
    try {
      picked = camera ? await picker.pickFromCamera() : await picker.pickFromGallery();
    } catch (_) {
      if (mounted) showMyProductsSnack(context, context.tr('myp.media.err.generic'));
      return;
    }
    if (picked == null || !mounted) return;
    final problem = checkImageFile(bytes: picked.bytes.length, mime: picked.mime);
    if (problem != null) {
      showMyProductsSnack(context, context.tr(problem));
      return;
    }
    final slot = _Upload(++_uploadSeq);
    setState(() => _uploads.add(slot));
    try {
      final up = await ref.read(mediaRepositoryProvider).uploadImage(
        picked,
        onProgress: (p) {
          if (mounted && _uploads.contains(slot)) setState(() => slot.progress = p);
        },
      );
      if (!mounted) return;
      final base = ref.read(apiClientProvider).baseUrl;
      setState(() {
        _uploads.remove(slot);
        if (_images.length < kMaxProductImages) {
          _images = <String>[..._images, resolveMediaUrl(base, up.url)];
          _errors = Map<String, String>.of(_errors)..remove('images');
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _uploads.remove(slot));
      showMyProductsSnack(context, context.tr(mediaErrorKey(e)));
    }
  }

  Widget _imageTile(BuildContext context, int i) {
    final base = ref.read(apiClientProvider).baseUrl;
    final rtl = Directionality.of(context) == TextDirection.rtl;
    final n = _images.length;
    Widget arrow(String keyId, IconData icon, int delta, String tip) => IconButton(
          key: ValueKey('myp-image-$keyId-$i'),
          tooltip: tip,
          iconSize: 18,
          padding: EdgeInsets.zero,
          visualDensity: VisualDensity.compact,
          constraints: const BoxConstraints.tightFor(width: 32, height: 32),
          icon: Icon(icon),
          onPressed: (i + delta < 0 || i + delta >= n)
              ? null
              : () => setState(() => _images = moveItem(_images, i, delta)),
        );
    return SizedBox(
      key: ValueKey('myp-image-tile-$i'),
      width: 96,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Stack(
            children: [
              AppNetworkImage(
                url: mediaThumbUrl(base, _images[i]),
                width: 96,
                height: 96,
                borderRadius: BorderRadius.circular(AppRadius.sm),
              ),
              if (i == 0)
                PositionedDirectional(
                  start: 4,
                  bottom: 4,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      context.tr('myp.media.cover'),
                      style: const TextStyle(color: Colors.white, fontSize: 10),
                    ),
                  ),
                ),
            ],
          ),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              arrow('earlier', rtl ? Icons.chevron_right : Icons.chevron_left, -1,
                  context.tr('myp.media.earlier')),
              IconButton(
                key: ValueKey('myp-image-remove-$i'),
                tooltip: context.tr('myp.media.remove'),
                iconSize: 18,
                padding: EdgeInsets.zero,
                visualDensity: VisualDensity.compact,
                constraints: const BoxConstraints.tightFor(width: 32, height: 32),
                icon: const Icon(Icons.close),
                onPressed: () => setState(() {
                  _images = <String>[..._images]..removeAt(i);
                }),
              ),
              arrow('later', rtl ? Icons.chevron_left : Icons.chevron_right, 1,
                  context.tr('myp.media.later')),
            ],
          ),
          ),
        ],
      ),
    );
  }

  Widget _uploadTile(_Upload u) => Container(
        key: ValueKey('myp-image-uploading-${u.id}'),
        width: 96,
        height: 96,
        decoration: BoxDecoration(
          color: AppColors.border.withOpacity(0.5),
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
        alignment: Alignment.center,
        child: SizedBox(
          width: 28,
          height: 28,
          child: CircularProgressIndicator(
            strokeWidth: 3,
            value: (u.progress > 0 && u.progress < 1) ? u.progress : null,
          ),
        ),
      );

  Future<void> _pickOrigin() async {
    final picked = await showLocationEditor(context, initial: _origin);
    if (picked != null) setState(() => _origin = picked);
  }

  Widget _label(String key) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.sm),
        child: Text(context.tr(key), style: const TextStyle(fontWeight: FontWeight.w800)),
      );

  Widget _section(String key) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.xl, bottom: AppSpacing.xs),
        child: Text(
          context.tr(key),
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.w800, color: AppColors.primary),
        ),
      );

  Widget _errorText(String? text) => text == null
      ? const SizedBox.shrink()
      : Padding(
          padding: const EdgeInsets.only(top: 6, left: 12, right: 12),
          child: Text(text, style: const TextStyle(color: AppColors.danger, fontSize: 12)),
        );

  TextInputType get _decimalKeyboard =>
      const TextInputType.numberWithOptions(decimal: true);

  @override
  Widget build(BuildContext context) {
    final title = context.tr(_isEdit ? 'myp.edit_title' : 'myp.new_title');
    Widget body;
    if (_loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_loadErrorKey != null) {
      body = ErrorState(message: context.tr(_loadErrorKey!), onRetry: _loadExisting);
    } else {
      body = _buildForm(context);
    }
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: body,
    );
  }

  Widget _buildForm(BuildContext context) {
    final lang = Localizations.localeOf(context).languageCode;
    final tree = ref.watch(productCategoriesProvider).valueOrNull ?? kFallbackCategories;
    var leaves = leafCategoriesFor(tree, _kind);
    if (_category.isNotEmpty && !leaves.any((n) => n.slug == _category)) {
      leaves = <CategoryNode>[
        CategoryNode(slug: _category, name: _category, nameAr: _category),
        ...leaves,
      ];
    }
    final status = _existing?.status;
    return ListView(
      key: const ValueKey('myp-editor'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        if (_existing != null && _existing!.isModerated)
          ModerationNotice(listing: _existing!),
        _section('myp.section.basics'),
        _label('myp.kind'),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final k in ListingKind.values)
              ChoiceChip(
                key: ValueKey('myp-kind-${k.json}'),
                label: Text(context.tr('myp.kind.${k.json}')),
                selected: _kind == k,
                onSelected: (_) => setState(() {
                  _kind = k;
                  final next = leafCategoriesFor(tree, k);
                  if (!next.any((n) => n.slug == _category)) _category = '';
                }),
              ),
          ],
        ),
        _label('myp.condition'),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final c in ItemCondition.values)
              ChoiceChip(
                key: ValueKey('myp-cond-${c.json}'),
                label: Text(context.tr('myp.cond.${c.json}')),
                selected: _condition == c,
                onSelected: (_) => setState(() => _condition = c),
              ),
          ],
        ),
        _label('myp.category'),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final n in leaves)
              ChoiceChip(
                key: ValueKey('myp-cat-${n.slug}'),
                label: Text(n.label(lang)),
                selected: _category == n.slug,
                onSelected: (_) => setState(() {
                  _category = n.slug;
                  _errors = Map<String, String>.of(_errors)..remove('category');
                }),
              ),
          ],
        ),
        _errorText(_err('category')),
        const SizedBox(height: AppSpacing.lg),
        TextField(
          key: const ValueKey('myp-title'),
          controller: _title,
          textInputAction: TextInputAction.next,
          onChanged: (_) => _clear('title'),
          decoration: InputDecoration(
            labelText: context.tr('myp.f.title'),
            errorText: _err('title'),
            errorMaxLines: 3,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        TextField(
          controller: _titleAr,
          onChanged: (_) => _clear('titleAr'),
          decoration: InputDecoration(
            labelText: context.tr('myp.f.title_ar'),
            errorText: _err('titleAr'),
            errorMaxLines: 3,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        TextField(
          controller: _description,
          minLines: 3,
          maxLines: 6,
          onChanged: (_) => _clear('description'),
          decoration: InputDecoration(
            labelText: context.tr('myp.f.description'),
            errorText: _err('description'),
            errorMaxLines: 3,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        TextField(
          controller: _descriptionAr,
          minLines: 2,
          maxLines: 6,
          onChanged: (_) => _clear('descriptionAr'),
          decoration: InputDecoration(
            labelText: context.tr('myp.f.description_ar'),
            errorText: _err('descriptionAr'),
            errorMaxLines: 3,
          ),
        ),
        _section('myp.section.price'),
        const SizedBox(height: AppSpacing.sm),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                key: const ValueKey('myp-price-min'),
                controller: _priceMin,
                keyboardType: _decimalKeyboard,
                textDirection: TextDirection.ltr,
                onChanged: (_) => _clear('priceMin'),
                decoration: InputDecoration(
                  labelText: context.tr('myp.f.price_min'),
                  errorText: _err('priceMin'),
                  errorMaxLines: 3,
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: TextField(
                key: const ValueKey('myp-price-max'),
                controller: _priceMax,
                keyboardType: _decimalKeyboard,
                textDirection: TextDirection.ltr,
                onChanged: (_) => _clear('priceMax'),
                decoration: InputDecoration(
                  labelText: context.tr('myp.f.price_max'),
                  errorText: _err('priceMax'),
                  errorMaxLines: 3,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        InputDecorator(
          decoration: InputDecoration(labelText: context.tr('myp.f.currency')),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              key: const ValueKey('myp-currency'),
              value: kProductCurrencies.contains(_currency) ? _currency : null,
              isExpanded: true,
              isDense: true,
              items: [
                for (final c in kProductCurrencies)
                  DropdownMenuItem<String>(value: c, child: Text(c)),
              ],
              onChanged: (v) {
                if (v != null) setState(() => _currency = v);
              },
            ),
          ),
        ),
        _label('myp.f.unit'),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final u in kProductUnits)
              ChoiceChip(
                key: ValueKey('myp-unit-$u'),
                label: Text(context.tr('myp.unit.$u')),
                selected: _unit == u,
                onSelected: (_) => setState(() => _unit = u),
              ),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),
        TextField(
          key: const ValueKey('myp-moq'),
          controller: _moq,
          keyboardType: TextInputType.number,
          textDirection: TextDirection.ltr,
          onChanged: (_) => _clear('moq'),
          decoration: InputDecoration(
            labelText: context.tr('myp.f.moq'),
            errorText: _err('moq'),
            errorMaxLines: 3,
          ),
        ),
        _section('myp.section.shipping'),
        _label('myp.f.incoterm'),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            ChoiceChip(
              label: Text(context.tr('myp.f.incoterm_none')),
              selected: _incoterm == null,
              onSelected: (_) => setState(() => _incoterm = null),
            ),
            for (final t in Incoterm.values)
              ChoiceChip(
                label: Text(t.json),
                selected: _incoterm == t,
                onSelected: (_) => setState(() => _incoterm = t),
              ),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                controller: _weight,
                keyboardType: _decimalKeyboard,
                textDirection: TextDirection.ltr,
                onChanged: (_) => _clear('weight'),
                decoration: InputDecoration(
                  labelText: context.tr('myp.f.weight'),
                  errorText: _err('weight'),
                  errorMaxLines: 3,
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: TextField(
                controller: _volume,
                keyboardType: _decimalKeyboard,
                textDirection: TextDirection.ltr,
                onChanged: (_) => _clear('volume'),
                decoration: InputDecoration(
                  labelText: context.tr('myp.f.volume'),
                  errorText: _err('volume'),
                  errorMaxLines: 3,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        HsCodePicker(controller: _hs),
        _errorText(_err('hs')),
        const SizedBox(height: AppSpacing.md),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                controller: _leadMin,
                keyboardType: TextInputType.number,
                textDirection: TextDirection.ltr,
                onChanged: (_) => _clear('lead'),
                decoration: InputDecoration(
                  labelText: context.tr('myp.f.lead_min'),
                  errorText: _err('lead'),
                  errorMaxLines: 3,
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: TextField(
                controller: _leadMax,
                keyboardType: TextInputType.number,
                textDirection: TextDirection.ltr,
                onChanged: (_) => _clear('lead'),
                decoration: InputDecoration(labelText: context.tr('myp.f.lead_max')),
              ),
            ),
          ],
        ),
        _section('myp.section.origin'),
        const SizedBox(height: AppSpacing.sm),
        AppCard(
          onTap: _pickOrigin,
          child: Row(
            children: [
              CountryFlag(countryCode: _origin.countryCode, size: 22),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Text(
                  locationLabel(context, _origin),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const Icon(Icons.edit_outlined, size: 20),
            ],
          ),
        ),
        _section('myp.section.images'),
        const SizedBox(height: AppSpacing.sm),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                key: const ValueKey('myp-image-gallery'),
                onPressed: () => _pickAndUpload(false),
                icon: const Icon(Icons.photo_library_outlined, size: 20),
                label: Text(
                  context.tr('myp.media.gallery'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: OutlinedButton.icon(
                key: const ValueKey('myp-image-camera'),
                onPressed: () => _pickAndUpload(true),
                icon: const Icon(Icons.photo_camera_outlined, size: 20),
                label: Text(
                  context.tr('myp.media.camera'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        Text(
          context.tr('myp.f.images_count', {
            'n': '${_images.length}',
            'max': '$kMaxProductImages',
          }),
          style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
        ),
        const SizedBox(height: AppSpacing.sm),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (var i = 0; i < _images.length; i++) _imageTile(context, i),
            for (final u in _uploads) _uploadTile(u),
          ],
        ),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextButton(
            key: const ValueKey('myp-image-url-toggle'),
            onPressed: () => setState(() => _showUrlInput = !_showUrlInput),
            child: Text(context.tr('myp.media.by_url')),
          ),
        ),
        if (_showUrlInput)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  key: const ValueKey('myp-image-input'),
                  controller: _imageInput,
                  keyboardType: TextInputType.url,
                  textDirection: TextDirection.ltr,
                  autocorrect: false,
                  onChanged: (_) {
                    if (_imageInputError != null) setState(() => _imageInputError = null);
                  },
                  onSubmitted: (_) => _addImage(),
                  decoration: InputDecoration(
                    labelText: context.tr('myp.f.image_url'),
                    errorText: _imageInputError == null ? null : context.tr(_imageInputError!),
                    errorMaxLines: 3,
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: OutlinedButton(
                  key: const ValueKey('myp-image-add'),
                  style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
                  onPressed: _addImage,
                  child: Text(context.tr('myp.f.add_image')),
                ),
              ),
            ],
          ),
        _errorText(_err('images')),
        const SizedBox(height: AppSpacing.xl),
        PrimaryButton(
          key: const ValueKey('myp-save'),
          label: context.tr(_isEdit ? 'myp.save' : 'myp.save_draft'),
          icon: Icons.save_outlined,
          loading: _busy,
          onPressed: _busy ? null : _save,
        ),
        if (_isEdit) ...[
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.md,
            runSpacing: AppSpacing.sm,
            children: [
              if (status == ListingStatus.published)
                OutlinedButton.icon(
                  key: const ValueKey('myp-editor-unpublish'),
                  onPressed: _busy
                      ? null
                      : () => _simpleAction(
                            titleKey: 'myp.confirm.unpublish_title',
                            messageKey: 'myp.confirm.unpublish_msg',
                            confirmKey: 'myp.unpublish',
                            okKey: 'myp.ok.unpublished',
                            run: (r, id) => r.unpublish(id),
                          ),
                  icon: const Icon(Icons.visibility_off_outlined),
                  label: Text(context.tr('myp.unpublish')),
                )
              else if (!(_existing?.isModerated ?? false))
                OutlinedButton.icon(
                  key: const ValueKey('myp-editor-publish'),
                  onPressed: _busy ? null : _publish,
                  icon: const Icon(Icons.publish),
                  label: Text(context.tr('myp.publish')),
                ),
              OutlinedButton.icon(
                key: const ValueKey('myp-editor-delete'),
                style: OutlinedButton.styleFrom(foregroundColor: AppColors.danger),
                onPressed: _busy
                    ? null
                    : () => _simpleAction(
                          titleKey: 'myp.confirm.delete_title',
                          messageKey: 'myp.confirm.delete_msg',
                          confirmKey: 'myp.delete',
                          okKey: 'myp.ok.deleted',
                          run: (r, id) => r.delete(id),
                        ),
                icon: const Icon(Icons.delete_outline),
                label: Text(context.tr('myp.delete')),
              ),
            ],
          ),
        ],
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

/// An image upload in flight (shown as a spinner tile).
class _Upload {
  _Upload(this.id);
  final int id;
  double progress = 0;
}
