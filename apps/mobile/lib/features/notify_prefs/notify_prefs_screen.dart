import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class NotifyPrefsScreen extends ConsumerStatefulWidget {
  const NotifyPrefsScreen({super.key});

  @override
  ConsumerState<NotifyPrefsScreen> createState() => _NotifyPrefsScreenState();
}

class _NotifyPrefsScreenState extends ConsumerState<NotifyPrefsScreen> {
  final TextEditingController _email = TextEditingController();
  NotifyPrefs? _draft;
  bool _loading = true;
  String? _loadError;
  bool _saving = false;
  String? _saveErrorKey;
  String? _saveErrorText;
  bool _saved = false;
  String? _emailErrorKey;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final p = await ref.read(notifyPrefsRepositoryProvider).get();
      if (!mounted) return;
      setState(() {
        _draft = p;
        _email.text = p.email ?? '';
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = describeError(e);
        _loading = false;
      });
    }
  }

  void _update(NotifyPrefs next) => setState(() {
        _draft = next;
        _saved = false;
      });

  Future<void> _pickTime({required bool start}) async {
    final d = _draft;
    if (d == null) return;
    final cur = parseHhmm(start ? d.quietStart : d.quietEnd) ??
        (hour: start ? 22 : 7, minute: 0);
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: cur.hour, minute: cur.minute),
    );
    if (picked == null || !mounted) return;
    final s = formatHhmm(picked.hour, picked.minute);
    _update(start ? d.copyWith(quietStart: s) : d.copyWith(quietEnd: s));
  }

  Future<void> _save() async {
    final d = _draft;
    if (d == null) return;
    final emailErr = validateDigestEmail(_email.text);
    if (emailErr != null) {
      setState(() => _emailErrorKey = emailErr);
      return;
    }
    setState(() {
      _emailErrorKey = null;
      _saving = true;
      _saveErrorKey = null;
      _saveErrorText = null;
      _saved = false;
    });
    try {
      final saved = await ref
          .read(notifyPrefsRepositoryProvider)
          .save(d.copyWith(email: _email.text.trim()));
      if (!mounted) return;
      setState(() {
        _draft = saved;
        _email.text = saved.email ?? '';
        _saving = false;
        _saved = true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        if (e is ApiException && e.isUnauthorized) {
          _saveErrorKey = 'notifyprefs.login_required';
        } else {
          _saveErrorKey = 'notifyprefs.save_failed';
          _saveErrorText = describeError(e);
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _draft;
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('notifyprefs.title'))),
      body: _loading
          ? const SingleChildScrollView(child: LoadingList(itemCount: 4))
          : (d == null
              ? ErrorState(message: _loadError ?? '', onRetry: _load)
              : _form(context, d)),
    );
  }

  Widget _form(BuildContext context, NotifyPrefs d) {
    final tzItems = <String>[
      if (!kTimezones.contains(d.timezone)) d.timezone,
      ...kTimezones,
    ];
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        Text(
          context.tr('notifyprefs.channels'),
          style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          context.tr('notifyprefs.in_app_note'),
          style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
        ),
        const SizedBox(height: AppSpacing.sm),
        for (final type in kAlertTypes)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: AppCard(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.lg,
                      vertical: AppSpacing.xs,
                    ),
                    child: Text(
                      context.tr('notifyprefs.type.$type'),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  for (final ch in kChannels)
                    SwitchListTile(
                      key: Key('np_${type}_$ch'),
                      dense: true,
                      title: Text(
                        context.tr('notifyprefs.channel.$ch'),
                        overflow: TextOverflow.ellipsis,
                      ),
                      value: d.isOn(type, ch),
                      onChanged: (v) => _update(d.withChannel(type, ch, v)),
                    ),
                ],
              ),
            ),
          ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.xs,
                ),
                child: Text(
                  context.tr('notifyprefs.quiet_title'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: Text(
                  context.tr('notifyprefs.quiet_hint'),
                  style: const TextStyle(
                    color: AppColors.textSecondary,
                    fontSize: 12,
                  ),
                ),
              ),
              SwitchListTile(
                key: const Key('np_quiet_enable'),
                title: Text(
                  context.tr('notifyprefs.quiet_enable'),
                  overflow: TextOverflow.ellipsis,
                ),
                value: d.hasQuietHours,
                onChanged: (v) => _update(
                  v
                      ? d.copyWith(
                          quietStart: d.quietStart ?? '22:00',
                          quietEnd: d.quietEnd ?? '07:00',
                        )
                      : d.copyWith(clearQuiet: true),
                ),
              ),
              if (d.hasQuietHours) ...[
                ListTile(
                  key: const Key('np_quiet_start'),
                  leading: const Icon(Icons.bedtime_outlined),
                  title: Text(context.tr('notifyprefs.quiet_start')),
                  trailing: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(d.quietStart ?? ''),
                  ),
                  onTap: () => _pickTime(start: true),
                ),
                ListTile(
                  key: const Key('np_quiet_end'),
                  leading: const Icon(Icons.wb_sunny_outlined),
                  title: Text(context.tr('notifyprefs.quiet_end')),
                  trailing: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(d.quietEnd ?? ''),
                  ),
                  onTap: () => _pickTime(start: false),
                ),
              ],
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.sm,
                  AppSpacing.lg,
                  AppSpacing.sm,
                ),
                child: InputDecorator(
                  decoration: InputDecoration(
                    labelText: context.tr('notifyprefs.timezone'),
                  ),
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      key: const Key('np_timezone'),
                      isExpanded: true,
                      value: d.timezone,
                      items: [
                        for (final tz in tzItems)
                          DropdownMenuItem<String>(
                            value: tz,
                            child: Text(tz, overflow: TextOverflow.ellipsis),
                          ),
                      ],
                      onChanged: (v) {
                        if (v != null) _update(d.copyWith(timezone: v));
                      },
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                context.tr('notifyprefs.language'),
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                children: [
                  ChoiceChip(
                    key: const Key('np_lang_ar'),
                    label: Text(context.tr('profile.language_ar')),
                    selected: d.language == 'ar',
                    onSelected: (_) => _update(d.copyWith(language: 'ar')),
                  ),
                  ChoiceChip(
                    key: const Key('np_lang_en'),
                    label: Text(context.tr('profile.language_en')),
                    selected: d.language == 'en',
                    onSelected: (_) => _update(d.copyWith(language: 'en')),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.lg),
              TextField(
                key: const Key('np_email'),
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                textDirection: TextDirection.ltr,
                onChanged: (_) {
                  if (_saved || _emailErrorKey != null) {
                    setState(() {
                      _saved = false;
                      _emailErrorKey = null;
                    });
                  }
                },
                decoration: InputDecoration(
                  labelText: context.tr('notifyprefs.email'),
                  helperText: context.tr('notifyprefs.email_hint'),
                  errorText: _emailErrorKey == null
                      ? null
                      : context.tr(_emailErrorKey!),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        if (_saveErrorKey != null)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: Text(
              context.tr(_saveErrorKey!) +
                  (_saveErrorText == null ? '' : ': $_saveErrorText'),
              key: const Key('np_save_error'),
              style: const TextStyle(color: AppColors.danger),
            ),
          ),
        if (_saved)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: Text(
              context.tr('notifyprefs.saved'),
              key: const Key('np_saved'),
              style: const TextStyle(color: AppColors.success),
            ),
          ),
        PrimaryButton(
          label: context.tr('notifyprefs.save'),
          loading: _saving,
          onPressed: _saving ? null : _save,
        ),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}
