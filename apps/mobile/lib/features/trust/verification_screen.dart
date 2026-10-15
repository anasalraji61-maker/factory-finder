import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/my_products/screens/my_products_screen.dart';
import 'package:factory_finder/features/trust/verification_badge.dart';
import 'package:factory_finder/features/trust/verification_form_sheet.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:factory_finder/features/trust/verification_thumbnails.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

Color _statusColor(String status) {
  switch (status) {
    case 'approved':
      return AppColors.success;
    case 'pending':
      return AppColors.warning;
    case 'rejected':
    case 'expired':
      return AppColors.danger;
    default:
      return AppColors.textSecondary;
  }
}

/// Status pill: pending / approved / rejected / withdrawn / expired.
class VerificationStatusChip extends StatelessWidget {
  const VerificationStatusChip({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Text(
        context.tr('ver.status.$status'),
        style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12),
      ),
    );
  }
}

class VerificationScreen extends ConsumerWidget {
  const VerificationScreen({super.key});

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final ok = await showVerificationSheet(context);
    if (ok != true) return;
    if (!context.mounted) return;
    ref.invalidate(myVerificationProvider);
    _snack(context, context.tr('ver.submit_ok'));
  }

  Future<void> _withdraw(
    BuildContext context,
    WidgetRef ref,
    VerificationDocument d,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('ver.withdraw_title')),
        content: Text(ctx.tr('ver.withdraw_msg')),
        actions: [
          TextButton(
            key: const ValueKey<String>('ver-withdraw-cancel'),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('ver.cancel')),
          ),
          TextButton(
            key: const ValueKey<String>('ver-withdraw-confirm'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('ver.withdraw')),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(verificationRepositoryProvider).withdraw(d.id);
      if (!context.mounted) return;
      ref.invalidate(myVerificationProvider);
      _snack(context, context.tr('ver.withdraw_ok'));
    } catch (e) {
      if (!context.mounted) return;
      ref.invalidate(myVerificationProvider);
      _snack(context, context.tr(verificationErrorKey(e), verificationErrorArgs(e)));
    }
  }

  void _snack(BuildContext context, String text) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(authProvider);
    final bypass = ref.watch(myProductsBypassGateProvider);
    final open = isVerifiedSupplier(me) || bypass;
    Widget body;
    if (me == null && !bypass) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Text(context.tr('ver.signin'), textAlign: TextAlign.center),
        ),
      );
    } else if (!open) {
      body = _gate(context);
    } else {
      body = _content(context, ref);
    }
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('ver.title'))),
      body: body,
    );
  }

  Widget _gate(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          AppCard(
            key: const ValueKey<String>('ver-gate-card'),
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.tr('ver.gate_title'),
                  style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(context.tr('ver.gate_msg')),
                const SizedBox(height: AppSpacing.lg),
                PrimaryButton(
                  label: context.tr('ver.gate_button'),
                  icon: Icons.storefront_outlined,
                  onPressed: () => context.push('/supplier-claim'),
                ),
              ],
            ),
          ),
        ],
      );

  Widget _content(BuildContext context, WidgetRef ref) {
    final docs = ref.watch(myVerificationProvider);
    return docs.when(
      loading: () => const SingleChildScrollView(child: LoadingList(itemCount: 3)),
      error: (e, _) {
        if (isSupplierGateError(e, notFoundCounts: true)) {
          // Claim revoked server-side: re-read /v1/me (rate limited, and it
          // only replaces state when something changed) and show the claim
          // prompt instead of an error.
          final auth = ref.read(authProvider.notifier);
          Future<void>.microtask(
            () => auth.refreshMe(minGap: const Duration(seconds: 30)),
          );
          return _gate(context);
        }
        return ErrorState(
        error: e,
        message: context.tr(verificationErrorKey(e), verificationErrorArgs(e)),
        onRetry: () => ref.invalidate(myVerificationProvider),
        );
      },
      data: (list) => ListView(
        key: const ValueKey<String>('ver-list'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Text(context.tr('ver.intro')),
          const SizedBox(height: AppSpacing.md),
          AppCard(
            key: const ValueKey<String>('ver-level-card'),
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Wrap(
              spacing: AppSpacing.md,
              runSpacing: AppSpacing.sm,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  context.tr('ver.level_title'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                list.level == 'none'
                    ? Text(
                        context.tr('ver.level.none'),
                        key: const ValueKey<String>('ver-level-none'),
                        style: TextStyle(color: AppColors.secondaryOf(context)),
                      )
                    : VerificationLevelChip(level: list.level),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(
            key: const ValueKey<String>('ver-add'),
            label: context.tr('ver.add'),
            icon: Icons.add,
            onPressed: () => _add(context, ref),
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            context.tr('ver.docs_title'),
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
          ),
          const SizedBox(height: AppSpacing.sm),
          if (list.items.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
              child: Text(
                context.tr('ver.empty'),
                key: const ValueKey<String>('ver-empty'),
                style: TextStyle(color: AppColors.secondaryOf(context)),
              ),
            )
          else
            for (final d in list.items)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: _docCard(context, ref, d),
              ),
        ],
      ),
    );
  }

  Widget _docCard(BuildContext context, WidgetRef ref, VerificationDocument d) {
    final secondary = TextStyle(color: AppColors.secondaryOf(context));
    final status = effectiveDocStatus(d);
    return AppCard(
      key: ValueKey<String>('ver-doc-${d.id}'),
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                context.tr('ver.type.${d.docType}'),
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              KeyedSubtree(
                key: ValueKey<String>('ver-status-${d.id}'),
                child: VerificationStatusChip(status: status),
              ),
            ],
          ),
          if (d.numberMasked != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Directionality(
              textDirection: TextDirection.ltr,
              child: Align(
                alignment: AlignmentDirectional.centerStart,
                child: Text(
                  context.tr('ver.number', {'n': d.numberMasked!}),
                  key: ValueKey<String>('ver-number-${d.id}'),
                  style: secondary,
                ),
              ),
            ),
          ],
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.md,
            runSpacing: 2,
            children: [
              if (d.issuingCountry.isNotEmpty)
                Text(context.tr('ver.country', {'c': d.issuingCountry}), style: secondary),
              if (d.expiresOn != null)
                Text(context.tr('ver.expires', {'d': d.expiresOn!}), style: secondary),
              Text(context.tr('ver.files_n', {'n': '${d.files.length}'}), style: secondary),
            ],
          ),
          if (d.files.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              key: ValueKey<String>('ver-thumbs-${d.id}'),
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (var i = 0; i < d.files.length; i++)
                  VerificationThumb(
                    key: ValueKey<String>('ver-thumb-${d.id}-$i'),
                    fileRef: d.files[i],
                    index: i + 1,
                  ),
              ],
            ),
          ],
          if (d.status == 'rejected' && d.reason != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              context.tr('ver.reason', {'r': d.reason!}),
              key: ValueKey<String>('ver-reason-${d.id}'),
              style: const TextStyle(color: AppColors.danger),
            ),
          ],
          if (canWithdraw(d))
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: TextButton(
                key: ValueKey<String>('ver-withdraw-${d.id}'),
                onPressed: () => _withdraw(context, ref, d),
                child: Text(context.tr('ver.withdraw')),
              ),
            ),
        ],
      ),
    );
  }
}
