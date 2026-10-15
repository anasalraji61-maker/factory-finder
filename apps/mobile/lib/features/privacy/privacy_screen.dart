import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:factory_finder/features/privacy/privacy_models.dart';
import 'package:factory_finder/features/privacy/privacy_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Every persisted settings key removed when the account is deleted.
const List<String> kLocalStateKeys = [
  StorageKeys.onboardingDone,
  StorageKeys.locale,
  StorageKeys.currency,
  StorageKeys.destination,
  StorageKeys.serverUrl,
  StorageKeys.refreshToken,
  StorageKeys.themeMode,
  StorageKeys.digitStyle,
  kSearchCacheSlot,
  kHomeFeedCacheSlot,
];

/// Settings -> Privacy & data: export my data, delete my account.
class PrivacyScreen extends ConsumerStatefulWidget {
  /// [onAccountGone] runs after the account was deleted and local state
  /// cleared; defaults to routing to `/onboarding`.
  const PrivacyScreen({super.key, this.onAccountGone});

  final VoidCallback? onAccountGone;

  @override
  ConsumerState<PrivacyScreen> createState() => _PrivacyScreenState();
}

class _PrivacyScreenState extends ConsumerState<PrivacyScreen> {
  final TextEditingController _password = TextEditingController();
  bool _exporting = false;
  bool _deleting = false;
  bool _gone = false;
  String? _exportError;
  String? _deleteError;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  String _errorText(Object e) {
    if (e is ApiException &&
        e.status == 429 &&
        e.retryAfterSeconds != null &&
        e.retryAfterSeconds! > 0) {
      return context.tr(
        'privacy.err.rate_limited_in',
        {'s': '${e.retryAfterSeconds}'},
      );
    }
    return context.tr(privacyErrorKey(e));
  }

  Future<void> _export() async {
    final repo = ref.read(privacyRepositoryProvider);
    setState(() {
      _exporting = true;
      _exportError = null;
    });
    ExportResult result;
    try {
      result = await repo.exportData();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _exporting = false;
        _exportError = _errorText(e);
      });
      return;
    }
    if (!mounted) return;
    setState(() => _exporting = false);
    await showDialog<void>(
      context: context,
      builder: (_) => ExportResultDialog(result: result),
    );
  }

  Future<void> _delete() async {
    final repo = ref.read(privacyRepositoryProvider);
    final auth = ref.read(authProvider.notifier);
    final store = ref.read(keyValueStoreProvider);
    final onboarding = ref.read(onboardingCompletedProvider.notifier);
    final role = ref.read(userRoleProvider.notifier);

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('privacy.confirm.title')),
        content: Text(ctx.tr('privacy.confirm.body')),
        actions: [
          TextButton(
            key: const ValueKey<String>('privacy-confirm-cancel'),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('privacy.confirm.cancel')),
          ),
          TextButton(
            key: const ValueKey<String>('privacy-confirm-delete'),
            style: TextButton.styleFrom(foregroundColor: AppColors.danger),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('privacy.confirm.delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _deleting = true;
      _deleteError = null;
    });
    DeletionResult result;
    try {
      result = await repo.deleteAccount(password: _password.text);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _deleting = false;
        _deleteError = _errorText(e);
      });
      return;
    }

    // Server revoked every session: drop tokens, persisted state, sign out.
    if (mounted) setState(() => _gone = true);
    auth.logout();
    for (final k in kLocalStateKeys) {
      try {
        await store.remove(k);
      } catch (_) {
        // best effort
      }
    }
    onboarding.state = false;
    role.state = UserRole.buyer;
    if (!mounted) return;

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _doneDialog(ctx, result),
    );
    if (!mounted) return;
    final done = widget.onAccountGone;
    if (done != null) {
      done();
    } else {
      context.go('/onboarding');
    }
  }

  Widget _doneDialog(BuildContext ctx, DeletionResult r) {
    String title;
    String body;
    if (r.isDeleted) {
      title = ctx.tr('privacy.done.deleted_title');
      body = ctx.tr('privacy.done.deleted_body');
    } else if (r.status == 'scheduled') {
      title = ctx.tr('privacy.done.scheduled_title');
      final d = r.scheduledDate;
      body = d == null
          ? ctx.tr('privacy.done.scheduled_nodate')
          : ctx.tr('privacy.done.scheduled_body', {'date': d});
    } else {
      title = ctx.tr('privacy.done.partial_title');
      final names = r.pendingServices;
      body = ctx.tr(
        'privacy.done.partial_body',
        {'names': names.isEmpty ? '-' : names.join(', ')},
      );
    }
    return AlertDialog(
      key: const ValueKey<String>('privacy-done-dialog'),
      title: Text(title),
      content: SingleChildScrollView(child: Text(body)),
      actions: [
        TextButton(
          key: const ValueKey<String>('privacy-done'),
          onPressed: () => Navigator.of(ctx).pop(),
          child: Text(ctx.tr('privacy.done.ok')),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final me = ref.watch(authProvider);
    final secondary = AppColors.secondaryOf(context);
    final small = Theme.of(context).textTheme.bodySmall;

    Widget body;
    if (_gone) {
      body = const SizedBox.shrink();
    } else if (me == null) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Text(
            context.tr('privacy.login_required'),
            key: const ValueKey<String>('privacy-login-required'),
            textAlign: TextAlign.center,
          ),
        ),
      );
    } else {
      body = ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: SizedBox(
              width: double.infinity,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(
                    header: true,
                    child: Text(
                      context.tr('privacy.export.title'),
                      style: const TextStyle(fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(context.tr('privacy.export.body'),
                      style: small?.copyWith(color: secondary)),
                  const SizedBox(height: AppSpacing.md),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      key: const ValueKey<String>('privacy-export'),
                      onPressed: _exporting ? null : _export,
                      icon: _exporting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.download_outlined),
                      label: Text(context.tr(_exporting
                          ? 'privacy.export.busy'
                          : 'privacy.export.button')),
                    ),
                  ),
                  if (_exportError != null) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      _exportError!,
                      key: const ValueKey<String>('privacy-export-error'),
                      style: const TextStyle(color: AppColors.danger),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: SizedBox(
              width: double.infinity,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(
                    header: true,
                    child: Text(
                      context.tr('privacy.delete.title'),
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        color: AppColors.danger,
                      ),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(context.tr('privacy.delete.intro')),
                  const SizedBox(height: AppSpacing.md),
                  Text(context.tr('privacy.delete.deleted_head'),
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text(context.tr('privacy.delete.deleted_body'),
                      style: small?.copyWith(color: secondary)),
                  const SizedBox(height: AppSpacing.sm),
                  Text(context.tr('privacy.delete.kept_head'),
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text(context.tr('privacy.delete.kept_body'),
                      style: small?.copyWith(color: secondary)),
                  const SizedBox(height: AppSpacing.md),
                  TextField(
                    key: const ValueKey<String>('privacy-password'),
                    controller: _password,
                    obscureText: true,
                    enabled: !_deleting,
                    autocorrect: false,
                    enableSuggestions: false,
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      labelText: context.tr('privacy.delete.password'),
                      hintText: context.tr('privacy.delete.password_hint'),
                      border: const OutlineInputBorder(),
                    ),
                  ),
                  if (_deleteError != null) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      _deleteError!,
                      key: const ValueKey<String>('privacy-delete-error'),
                      style: const TextStyle(color: AppColors.danger),
                    ),
                  ],
                  const SizedBox(height: AppSpacing.md),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      key: const ValueKey<String>('privacy-delete'),
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.danger,
                        foregroundColor: Colors.white,
                      ),
                      onPressed: (_deleting || _password.text.isEmpty)
                          ? null
                          : _delete,
                      icon: _deleting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.delete_forever_outlined),
                      label: Text(context.tr(_deleting
                          ? 'privacy.delete.busy'
                          : 'privacy.delete.button')),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('privacy.title'))),
      body: body,
    );
  }
}

/// Shows size, partial warning and copy actions for a finished export.
class ExportResultDialog extends StatefulWidget {
  const ExportResultDialog({super.key, required this.result});

  final ExportResult result;

  @override
  State<ExportResultDialog> createState() => _ExportResultDialogState();
}

class _ExportResultDialogState extends State<ExportResultDialog> {
  bool _copied = false;

  String _summary(BuildContext context) {
    final r = widget.result;
    final lines = <String>[
      context.tr('privacy.export.summary_head'),
      context.tr('privacy.export.size', {'size': formatByteSize(r.sizeBytes)}),
      if (r.generatedAt != null)
        context.tr('privacy.export.generated', {'date': r.generatedAt!}),
      for (final s in r.services)
        context.tr('privacy.export.summary_service', {
          'name': s.name,
          'state': s.ok
              ? context.tr('privacy.export.state_ok')
              : context.tr('privacy.export.state_error',
                  {'code': s.error ?? '?'}),
        }),
    ];
    return lines.join('\n');
  }

  Future<void> _copy(String text) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    setState(() => _copied = true);
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    return AlertDialog(
      key: const ValueKey<String>('privacy-export-dialog'),
      title: Text(context.tr('privacy.export.ready')),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              context.tr('privacy.export.size',
                  {'size': formatByteSize(r.sizeBytes)}),
              key: const ValueKey<String>('privacy-export-size'),
            ),
            if (r.generatedAt != null)
              Text(context.tr(
                  'privacy.export.generated', {'date': r.generatedAt!})),
            if (r.partial) ...[
              const SizedBox(height: AppSpacing.md),
              Text(
                context.tr('privacy.export.partial_title'),
                key: const ValueKey<String>('privacy-export-partial'),
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppColors.warning,
                ),
              ),
              Text(context.tr('privacy.export.partial_body')),
              for (final s in r.failed)
                Text('${s.name}: ${s.error ?? '?'}'),
            ],
            if (r.truncatedServices.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(context.tr('privacy.export.truncated', {
                'names': r.truncatedServices.map((s) => s.name).join(', '),
              })),
            ],
            if (_copied) ...[
              const SizedBox(height: AppSpacing.md),
              Text(
                context.tr('privacy.export.copied'),
                key: const ValueKey<String>('privacy-export-copied'),
                style: const TextStyle(color: AppColors.success),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          key: const ValueKey<String>('privacy-copy-summary'),
          onPressed: () => _copy(_summary(context)),
          child: Text(context.tr('privacy.export.copy_summary')),
        ),
        TextButton(
          key: const ValueKey<String>('privacy-copy-json'),
          onPressed: () => _copy(r.toPrettyJson()),
          child: Text(context.tr('privacy.export.copy_json')),
        ),
        TextButton(
          key: const ValueKey<String>('privacy-export-close'),
          onPressed: () => Navigator.of(context).pop(),
          child: Text(context.tr('privacy.close')),
        ),
      ],
    );
  }
}
