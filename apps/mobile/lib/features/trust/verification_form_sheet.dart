import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_logic.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Opens the submit form. Resolves to true when a document was submitted.
Future<bool?> showVerificationSheet(BuildContext context) =>
    showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const VerificationFormSheet(),
    );

/// Media kind used for verification images (contract MediaKind).
const String kVerificationMediaKind = 'attachment';

class VerificationFormSheet extends ConsumerStatefulWidget {
  const VerificationFormSheet({super.key});

  @override
  ConsumerState<VerificationFormSheet> createState() => _VerificationFormSheetState();
}

class _VerificationFormSheetState extends ConsumerState<VerificationFormSheet> {
  final TextEditingController _country = TextEditingController();
  final TextEditingController _number = TextEditingController();
  final TextEditingController _expiry = TextEditingController();
  String? _type;
  bool _consent = false;
  bool _busy = false;
  int _uploading = 0;
  List<String> _files = <String>[];
  Map<String, String> _errors = <String, String>{};
  Object? _submitError;

  @override
  void dispose() {
    _country.dispose();
    _number.dispose();
    _expiry.dispose();
    super.dispose();
  }

  VerificationDraft _draft() => VerificationDraft(
        docType: _type,
        country: _country.text,
        number: _number.text,
        expiresOn: _expiry.text,
        consent: _consent,
        files: _files,
      );

  void _clear(String field) {
    if (_errors.containsKey(field) || _submitError != null) {
      setState(() {
        _errors = Map<String, String>.of(_errors)..remove(field);
        _submitError = null;
      });
    }
  }

  void _setError(String field, String key) =>
      setState(() => _errors = Map<String, String>.of(_errors)..[field] = key);

  Future<void> _pick(bool camera) async {
    if (_files.length + _uploading >= kVerificationMaxFiles) {
      _setError('files', 'ver.err.files');
      return;
    }
    final picker = ref.read(imagePickServiceProvider);
    PickedImage? picked;
    try {
      picked = camera ? await picker.pickFromCamera() : await picker.pickFromGallery();
    } catch (_) {
      if (mounted) _setError('files', 'myp.media.err.generic');
      return;
    }
    if (picked == null || !mounted) return;
    final problem = checkImageFile(bytes: picked.bytes.length, mime: picked.mime);
    if (problem != null) {
      _setError('files', problem);
      return;
    }
    setState(() => _uploading++);
    try {
      final up = await ref
          .read(mediaRepositoryProvider)
          .uploadImage(picked, kind: kVerificationMediaKind);
      if (!mounted) return;
      setState(() {
        _uploading--;
        if (_files.length < kVerificationMaxFiles) _files = <String>[..._files, up.url];
        _errors = Map<String, String>.of(_errors)..remove('files');
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _uploading--);
      _setError('files', mediaErrorKey(e));
    }
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: now.add(const Duration(days: 365)),
      firstDate: now,
      lastDate: DateTime(now.year + 50),
    );
    if (picked == null || !mounted) return;
    _expiry.text = formatIsoDate(picked);
    _clear('expiry');
  }

  Future<void> _submit() async {
    final errors = validateVerificationDraft(_draft());
    if (_uploading > 0) errors['files'] = 'myp.media.wait_uploads';
    if (errors.isNotEmpty) {
      setState(() {
        _errors = errors;
        _submitError = null;
      });
      return;
    }
    setState(() {
      _busy = true;
      _errors = <String, String>{};
      _submitError = null;
    });
    try {
      await ref.read(verificationRepositoryProvider).submit(_draft());
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _submitError = e;
      });
    }
  }

  Widget _error(BuildContext context, String? key, [Map<String, String> args = const {}]) {
    if (key == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.xs),
      child: Text(
        context.tr(key, args),
        style: const TextStyle(color: AppColors.danger, fontSize: 13),
      ),
    );
  }

  Widget _label(BuildContext context, String key) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.xs),
        child: Text(
          context.tr(key),
          style: const TextStyle(fontWeight: FontWeight.w800),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final needsNumber = docTypeNeedsNumber(_type);
    final submitError = _submitError;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SingleChildScrollView(
          key: const ValueKey<String>('ver-form'),
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            0,
            AppSpacing.lg,
            AppSpacing.lg,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                context.tr('ver.sheet_title'),
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w900),
              ),
              _label(context, 'ver.f.type'),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final t in kVerificationDocTypes)
                    ChoiceChip(
                      key: ValueKey<String>('ver-type-$t'),
                      label: Text(context.tr('ver.type.$t')),
                      selected: _type == t,
                      onSelected: (_) {
                        setState(() {
                          _type = t;
                          if (!docTypeNeedsNumber(t)) _number.clear();
                          _errors = Map<String, String>.of(_errors)
                            ..remove('type')
                            ..remove('number');
                          _submitError = null;
                        });
                      },
                    ),
                ],
              ),
              _error(context, _errors['type']),
              const SizedBox(height: AppSpacing.md),
              TextField(
                key: const ValueKey<String>('ver-country'),
                controller: _country,
                enabled: !_busy,
                textDirection: TextDirection.ltr,
                textCapitalization: TextCapitalization.characters,
                autocorrect: false,
                inputFormatters: [
                  LengthLimitingTextInputFormatter(2),
                  FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z]')),
                ],
                decoration: InputDecoration(
                  labelText: context.tr('ver.f.country'),
                  hintText: context.tr('ver.f.country_hint'),
                  errorText: _errors['country'] == null
                      ? null
                      : context.tr(_errors['country']!),
                  errorMaxLines: 3,
                ),
                onChanged: (_) => _clear('country'),
              ),
              const SizedBox(height: AppSpacing.md),
              if (needsNumber)
                TextField(
                  key: const ValueKey<String>('ver-number'),
                  controller: _number,
                  enabled: !_busy,
                  textDirection: TextDirection.ltr,
                  autocorrect: false,
                  inputFormatters: [LengthLimitingTextInputFormatter(kVerificationNumberMax)],
                  decoration: InputDecoration(
                    labelText: context.tr('ver.f.number'),
                    errorText: _errors['number'] == null
                        ? null
                        : context.tr(_errors['number']!),
                    errorMaxLines: 3,
                  ),
                  onChanged: (_) => _clear('number'),
                )
              else
                Text(
                  context.tr('ver.f.number_none'),
                  key: const ValueKey<String>('ver-number-none'),
                  style: TextStyle(color: AppColors.secondaryOf(context)),
                ),
              const SizedBox(height: AppSpacing.md),
              TextField(
                key: const ValueKey<String>('ver-expiry'),
                controller: _expiry,
                enabled: !_busy,
                textDirection: TextDirection.ltr,
                keyboardType: TextInputType.datetime,
                autocorrect: false,
                inputFormatters: [
                  LengthLimitingTextInputFormatter(10),
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9-]')),
                ],
                decoration: InputDecoration(
                  labelText: context.tr('ver.f.expiry'),
                  hintText: context.tr('ver.f.expiry_hint'),
                  errorText: _errors['expiry'] == null
                      ? null
                      : context.tr(_errors['expiry']!),
                  errorMaxLines: 3,
                  suffixIcon: IconButton(
                    key: const ValueKey<String>('ver-pick-date'),
                    tooltip: context.tr('ver.f.pick_date'),
                    icon: const Icon(Icons.calendar_today_outlined),
                    onPressed: _busy ? null : _pickDate,
                  ),
                ),
                onChanged: (_) => _clear('expiry'),
              ),
              _label(context, 'ver.f.files'),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  OutlinedButton.icon(
                    key: const ValueKey<String>('ver-gallery'),
                    onPressed: _busy ? null : () => _pick(false),
                    icon: const Icon(Icons.photo_library_outlined),
                    label: Text(context.tr('ver.f.gallery')),
                  ),
                  OutlinedButton.icon(
                    key: const ValueKey<String>('ver-camera'),
                    onPressed: _busy ? null : () => _pick(true),
                    icon: const Icon(Icons.photo_camera_outlined),
                    label: Text(context.tr('ver.f.camera')),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                context.tr('ver.f.files_count', {
                  'n': '${_files.length}',
                  'max': '$kVerificationMaxFiles',
                }),
                style: TextStyle(color: AppColors.secondaryOf(context)),
              ),
              if (_files.isNotEmpty || _uploading > 0) ...[
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.xs,
                  children: [
                    for (var i = 0; i < _files.length; i++)
                      InputChip(
                        key: ValueKey<String>('ver-file-$i'),
                        avatar: const Icon(Icons.image_outlined, size: 18),
                        label: Text('${i + 1}'),
                        deleteButtonTooltipMessage: context.tr('ver.f.remove'),
                        onDeleted: _busy
                            ? null
                            : () => setState(() {
                                  _files = <String>[..._files]..removeAt(i);
                                }),
                      ),
                    if (_uploading > 0)
                      Chip(
                        key: const ValueKey<String>('ver-file-uploading'),
                        avatar: const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        label: Text(context.tr('ver.f.uploading')),
                      ),
                  ],
                ),
              ],
              _error(context, _errors['files']),
              const SizedBox(height: AppSpacing.md),
              CheckboxListTile(
                key: const ValueKey<String>('ver-consent'),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _consent,
                onChanged: _busy
                    ? null
                    : (v) => setState(() {
                          _consent = v ?? false;
                          _errors = Map<String, String>.of(_errors)..remove('consent');
                          _submitError = null;
                        }),
                title: Text(context.tr('ver.f.consent')),
              ),
              _error(context, _errors['consent']),
              if (submitError != null)
                Container(
                  key: const ValueKey<String>('ver-submit-error'),
                  margin: const EdgeInsets.only(top: AppSpacing.md),
                  child: _error(
                    context,
                    verificationErrorKey(submitError),
                    verificationErrorArgs(submitError),
                  ),
                ),
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                key: const ValueKey<String>('ver-submit'),
                label: context.tr('ver.submit'),
                icon: Icons.send_outlined,
                loading: _busy,
                onPressed: _busy ? null : _submit,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
