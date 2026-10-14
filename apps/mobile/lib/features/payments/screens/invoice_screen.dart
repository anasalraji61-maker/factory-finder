import 'dart:async';

import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/payments/payments_models.dart';
import 'package:factory_finder/features/payments/payments_repository.dart';
import 'package:factory_finder/features/payments/widgets/invoice_widgets.dart';
import 'package:factory_finder/features/requests/screens/create_request_screen.dart'
    show formatDate;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const Duration kInvoicePollInterval = Duration(seconds: 8);

class InvoiceScreen extends ConsumerStatefulWidget {
  const InvoiceScreen({
    super.key,
    required this.invoiceId,
    this.pollInterval = kInvoicePollInterval,
  });

  final String invoiceId;
  final Duration pollInterval;

  @override
  ConsumerState<InvoiceScreen> createState() => _InvoiceScreenState();
}

class _InvoiceScreenState extends ConsumerState<InvoiceScreen> {
  Invoice? _invoice;
  Object? _error;
  bool _fetching = false;
  bool _cancelling = false;
  DateTime _now = DateTime.now().toUtc();
  Timer? _pollTimer;
  Timer? _tickTimer;

  @override
  void initState() {
    super.initState();
    _fetch();
    _tickTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _now = DateTime.now().toUtc());
    });
    _pollTimer = Timer.periodic(widget.pollInterval, (_) {
      if (!mounted) return;
      final inv = _invoice;
      if (inv != null && inv.status.isPollable) _fetch();
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _tickTimer?.cancel();
    super.dispose();
  }

  Future<void> _fetch() async {
    if (_fetching) return;
    _fetching = true;
    final repo = ref.read(paymentsRepositoryProvider);
    try {
      final inv = await repo.get(widget.invoiceId);
      if (!mounted) return;
      setState(() {
        _invoice = inv;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      // Keep showing the last good invoice if a background poll fails.
      if (_invoice == null) setState(() => _error = e);
    } finally {
      _fetching = false;
    }
  }

  Future<void> _copy(String value) async {
    try {
      await Clipboard.setData(ClipboardData(text: value));
    } catch (_) {
      return;
    }
    if (!mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(context.tr('pay.copied'))));
  }

  Future<void> _cancel() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('pay.cancel.title')),
        content: Text(ctx.tr('pay.cancel.msg')),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('pay.cancel.keep')),
          ),
          FilledButton(
            key: const Key('invoice_cancel_confirm'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('pay.cancel.confirm')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final repo = ref.read(paymentsRepositoryProvider);
    setState(() => _cancelling = true);
    try {
      final inv = await repo.cancel(widget.invoiceId);
      if (!mounted) return;
      setState(() {
        _invoice = inv;
        _cancelling = false;
      });
      ref.invalidate(dealInvoicesProvider(inv.dealId));
      _snack(context.tr('pay.cancelled'));
    } catch (e) {
      if (!mounted) return;
      setState(() => _cancelling = false);
      _snack(context.tr(invoiceErrorKey(e)));
    }
  }

  void _snack(String text) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) {
    final inv = _invoice;
    Widget body;
    if (inv == null && _error != null) {
      body = ErrorState(
        message: context.tr(invoiceErrorKey(_error!)),
        onRetry: () {
          setState(() => _error = null);
          _fetch();
        },
      );
    } else if (inv == null) {
      body = const LoadingList(itemCount: 3);
    } else {
      body = _buildInvoice(context, inv);
    }
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('pay.invoice.title'))),
      body: body,
    );
  }

  Widget _buildInvoice(BuildContext context, Invoice inv) {
    final theme = Theme.of(context);
    final left = invoiceTimeLeft(inv.expiresAt, _now);
    final showCountdown = inv.status.showsPayDetails;
    final reason = inv.statusReason;
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        AppCard(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      context.tr('pay.kind.${inv.kind.json}'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  InvoiceStatusChip(status: inv.status),
                ],
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                context.tr('pay.amount'),
                style: const TextStyle(color: AppColors.textSecondary),
              ),
              MoneyText(
                inv.amount,
                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 26),
              ),
              if (showCountdown) ...[
                const SizedBox(height: AppSpacing.md),
                if (left == Duration.zero)
                  Text(
                    context.tr('pay.expired_now'),
                    style: const TextStyle(color: AppColors.danger),
                  )
                else
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          context.tr('pay.expires_in'),
                          style: const TextStyle(color: AppColors.textSecondary),
                        ),
                      ),
                      Directionality(
                        textDirection: TextDirection.ltr,
                        child: Text(
                          formatCountdown(left),
                          key: const Key('invoice_countdown'),
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ),
                    ],
                  ),
              ],
              if (inv.status == InvoiceStatus.confirming) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(context.tr('pay.confirmations', {'n': '${inv.confirmations}'})),
              ],
              if (inv.status == InvoiceStatus.paid && inv.paidAt != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        context.tr('pay.paid_at'),
                        style: const TextStyle(color: AppColors.textSecondary),
                      ),
                    ),
                    Directionality(
                      textDirection: TextDirection.ltr,
                      child: Text(formatDate(inv.paidAt!.toLocal())),
                    ),
                  ],
                ),
              ],
              if (reason != null && !inv.status.showsPayDetails) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  reason == 'cancelled' ? context.tr('pay.reason.cancelled') : reason,
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
              ],
              if (inv.memo.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                _CopyRow(
                  label: context.tr('pay.memo'),
                  value: inv.memo,
                  copyKey: const Key('invoice_copy_memo'),
                  onCopy: _copy,
                ),
              ],
            ],
          ),
        ),
        if (inv.status.showsPayDetails) ...[
          const SizedBox(height: AppSpacing.lg),
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.tr('pay.details.title'),
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: AppSpacing.sm),
                if (inv.payAddress == null && inv.payUrl == null)
                  Text(context.tr('pay.no_details'))
                else ...[
                  if (inv.payAmount != null)
                    _CopyRow(
                      label: context.tr('pay.send_exact'),
                      value: '${inv.payAmount!.amount} ${inv.payAmount!.currency}',
                      copyValue: inv.payAmount!.amount,
                      copyKey: const Key('invoice_copy_amount'),
                      onCopy: _copy,
                    ),
                  if (inv.payAddress != null)
                    _CopyRow(
                      label: context.tr('pay.address'),
                      value: inv.payAddress!,
                      copyKey: const Key('invoice_copy_address'),
                      onCopy: _copy,
                    ),
                  if (inv.payUrl != null)
                    _CopyRow(
                      label: context.tr('pay.url'),
                      value: inv.payUrl!,
                      copyKey: const Key('invoice_copy_url'),
                      onCopy: _copy,
                    ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    context.tr('pay.instructions'),
                    style: const TextStyle(color: AppColors.textSecondary),
                  ),
                ],
              ],
            ),
          ),
        ],
        const SizedBox(height: AppSpacing.lg),
        Container(
          key: const Key('invoice_disclaimer'),
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: AppColors.warning.withOpacity(0.12),
            borderRadius: BorderRadius.circular(AppRadius.sm),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.warning_amber_rounded, color: AppColors.warning),
              const SizedBox(width: AppSpacing.sm),
              Expanded(child: Text(context.tr('pay.disclaimer'))),
            ],
          ),
        ),
        if (inv.status.isCancellable) ...[
          const SizedBox(height: AppSpacing.lg),
          OutlinedButton.icon(
            key: const Key('invoice_cancel_button'),
            onPressed: _cancelling ? null : _cancel,
            icon: const Icon(Icons.close),
            label: Text(context.tr('pay.cancel')),
          ),
        ],
      ],
    );
  }
}

class _CopyRow extends StatelessWidget {
  const _CopyRow({
    required this.label,
    required this.value,
    required this.copyKey,
    required this.onCopy,
    this.copyValue,
  });

  final String label;
  final String value;
  final String? copyValue;
  final Key copyKey;
  final Future<void> Function(String) onCopy;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 6),
        Text(label, style: const TextStyle(color: AppColors.textSecondary)),
        Row(
          children: [
            Expanded(
              child: Directionality(
                textDirection: TextDirection.ltr,
                child: Text(
                  value,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
            ),
            IconButton(
              key: copyKey,
              tooltip: context.tr('pay.copy'),
              icon: const Icon(Icons.copy, size: 20),
              onPressed: () => onCopy(copyValue ?? value),
            ),
          ],
        ),
      ],
    );
  }
}
