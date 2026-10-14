import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/payments/payments_models.dart';
import 'package:factory_finder/features/payments/payments_repository.dart';
import 'package:factory_finder/features/payments/widgets/invoice_widgets.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// "Commission & payment" block of an accepted deal: its invoices plus
/// actions to create one.
class DealPaymentSection extends ConsumerStatefulWidget {
  const DealPaymentSection({super.key, required this.deal});

  final Deal deal;

  @override
  ConsumerState<DealPaymentSection> createState() => _DealPaymentSectionState();
}

class _DealPaymentSectionState extends ConsumerState<DealPaymentSection> {
  InvoiceKind? _creating;

  Future<void> _create(InvoiceKind kind) async {
    if (_creating != null) return;
    final repo = ref.read(paymentsRepositoryProvider);
    setState(() => _creating = kind);
    String message;
    try {
      await repo.create(widget.deal, kind);
      if (!mounted) return;
      ref.invalidate(dealInvoicesProvider(widget.deal.id));
      message = context.tr('pay.created');
    } catch (e) {
      if (!mounted) return;
      message = context.tr(invoiceErrorKey(e));
    }
    if (!mounted) return;
    setState(() => _creating = null);
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(dealInvoicesProvider(widget.deal.id));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: context.tr('pay.section.title')),
        async.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpacing.lg),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (e, _) => ErrorState(
            message: context.tr(invoiceErrorKey(e)),
            onRetry: () => ref.invalidate(dealInvoicesProvider(widget.deal.id)),
          ),
          data: (items) {
            if (items.isEmpty) {
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
                child: Text(
                  context.tr('pay.section.empty'),
                  style: const TextStyle(color: AppColors.textSecondary),
                ),
              );
            }
            return Column(
              children: [
                for (final inv in items)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: AppCard(
                      onTap: () => context.push('/invoice/${inv.id}'),
                      padding: const EdgeInsets.all(AppSpacing.md),
                      child: Row(
                        key: Key('deal_invoice_${inv.id}'),
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  context.tr('pay.kind.${inv.kind.json}'),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(fontWeight: FontWeight.w700),
                                ),
                                MoneyText(inv.amount),
                              ],
                            ),
                          ),
                          const SizedBox(width: AppSpacing.sm),
                          InvoiceStatusChip(status: inv.status),
                        ],
                      ),
                    ),
                  ),
              ],
            );
          },
        ),
        const SizedBox(height: AppSpacing.sm),
        SizedBox(
          width: double.infinity,
          child: PrimaryButton(
            key: const Key('create_commission_invoice'),
            label: context.tr('pay.create.commission'),
            icon: Icons.receipt_long_outlined,
            loading: _creating == InvoiceKind.commission,
            onPressed: _creating == null
                ? () => _create(InvoiceKind.commission)
                : null,
          ),
        ),
        const SizedBox(height: AppSpacing.xs),
        SizedBox(
          width: double.infinity,
          child: TextButton(
            key: const Key('create_deal_payment_invoice'),
            onPressed: _creating == null
                ? () => _create(InvoiceKind.dealPayment)
                : null,
            child: Text(
              context.tr('pay.create.deal_payment'),
              maxLines: 2,
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ],
    );
  }
}
