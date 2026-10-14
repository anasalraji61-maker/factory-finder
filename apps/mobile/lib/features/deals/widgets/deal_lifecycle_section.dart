import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

String _two(int n) => n.toString().padLeft(2, '0');

String dealDateTimeLabel(DateTime d) {
  final l = d.toLocal();
  return '${l.year}/${_two(l.month)}/${_two(l.day)} ${_two(l.hour)}:${_two(l.minute)}';
}

Color dealStatusColor(String status) {
  switch (status) {
    case kDealCompleted:
    case kDealPaid:
      return AppColors.success;
    case kDealInFulfilment:
      return AppColors.primary;
    case 'disputed':
    case 'refunded':
    case 'cancelled':
      return AppColors.danger;
    default:
      return AppColors.warning;
  }
}

Color _paymentColor(String? s) {
  switch (s) {
    case 'paid':
      return AppColors.success;
    case 'open':
      return AppColors.warning;
    case 'refunded':
      return AppColors.danger;
    default:
      return AppColors.textSecondary;
  }
}

/// Overflow-safe rounded chip (single line, ellipsis).
class DealChip extends StatelessWidget {
  const DealChip({super.key, required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12),
      ),
    );
  }
}

/// Status chip plus the commission / supplier-payment chips of a deal.
class DealStatusChips extends StatelessWidget {
  const DealStatusChips({super.key, required this.deal});

  final Deal deal;

  @override
  Widget build(BuildContext context) {
    String pay(String kind, String? s) => context.tr('deals.pay.$kind', {
          's': context.tr('deals.pay.${s ?? 'none'}'),
        });
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.xs,
      children: [
        DealChip(
          key: const Key('deal_status_chip'),
          label: context.tr('deals.status.${deal.status}'),
          color: dealStatusColor(deal.status),
        ),
        DealChip(
          key: const Key('deal_commission_chip'),
          label: pay('commission', deal.payment.commission),
          color: _paymentColor(deal.payment.commission),
        ),
        DealChip(
          key: const Key('deal_payment_chip'),
          label: pay('deal_payment', deal.payment.dealPayment),
          color: _paymentColor(deal.payment.dealPayment),
        ),
      ],
    );
  }
}

/// Oldest-first event log of a deal.
class DealEventsTimeline extends StatelessWidget {
  const DealEventsTimeline({super.key, required this.events});

  final List<DealEvent> events;

  static IconData _icon(String action) {
    switch (action) {
      case 'payment_paid':
        return Icons.payments_outlined;
      case 'payment_refunded':
        return Icons.undo;
      case 'fulfilment_started':
        return Icons.precision_manufacturing_outlined;
      case 'delivered':
        return Icons.local_shipping_outlined;
      case 'receipt_confirmed':
        return Icons.task_alt;
    }
    return Icons.circle_outlined;
  }

  @override
  Widget build(BuildContext context) {
    if (events.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Text(
          context.tr('deals.events.empty'),
          style: const TextStyle(color: AppColors.textSecondary),
        ),
      );
    }
    final theme = Theme.of(context);
    return Column(
      children: [
        for (var i = 0; i < events.length; i++)
          IntrinsicHeight(
            key: Key('deal_event_${events[i].seq}'),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  width: 36,
                  child: Column(
                    children: [
                      Container(
                        width: 32,
                        height: 32,
                        decoration: BoxDecoration(
                          color: AppColors.primary.withOpacity(0.12),
                          shape: BoxShape.circle,
                        ),
                        child: Icon(
                          _icon(events[i].action),
                          size: 18,
                          color: AppColors.primary,
                        ),
                      ),
                      if (i != events.length - 1)
                        Expanded(child: Container(width: 2, color: AppColors.border)),
                    ],
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.md),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _title(context, events[i].action),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        Text(
                          [
                            context.tr('deals.actor.${events[i].actorRole}'),
                            if (events[i].createdAt != null)
                              dealDateTimeLabel(events[i].createdAt!),
                          ].join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: AppColors.textSecondary),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  static String _title(BuildContext context, String action) {
    final key = 'deals.event.$action';
    final text = context.tr(key);
    return text == key ? action : text;
  }
}

/// "Deal progress" block: status chips, role-aware actions, event timeline.
class DealLifecycleSection extends ConsumerStatefulWidget {
  const DealLifecycleSection({super.key, required this.deal, required this.role});

  final Deal deal;
  final DealRole role;

  @override
  ConsumerState<DealLifecycleSection> createState() => _DealLifecycleSectionState();
}

class _DealLifecycleSectionState extends ConsumerState<DealLifecycleSection> {
  String? _busy;

  @override
  void initState() {
    super.initState();
    ref.read(dealsRepositoryProvider).track(widget.deal);
  }

  Future<void> _run(
    String name,
    Future<Deal> Function(DealsRepository repo) call,
  ) async {
    if (_busy != null) return;
    final repo = ref.read(dealsRepositoryProvider);
    setState(() => _busy = name);
    String message;
    try {
      final updated = await call(repo);
      if (!mounted) return;
      ref.read(acceptedDealsProvider.notifier).update(
            (m) => <String, Deal>{...m, updated.requestId: updated},
          );
      ref.invalidate(dealEventsProvider(updated.id));
      message = context.tr('deals.done.$name');
    } catch (e) {
      if (!mounted) return;
      message = context.tr(dealErrorKey(e));
    }
    if (!mounted) return;
    setState(() => _busy = null);
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    messenger.showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _confirm() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('deals.confirm.title')),
        content: Text(ctx.tr('deals.confirm.msg')),
        actions: [
          TextButton(
            key: const Key('confirm_receipt_no'),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('deals.confirm.no')),
          ),
          FilledButton(
            key: const Key('confirm_receipt_yes'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('deals.confirm.yes')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _run('confirm', (r) => r.confirmReceipt(widget.deal.id));
  }

  String? _hintKey(Deal d, DealActions a) {
    switch (d.status) {
      case kDealPendingPayment:
        return 'deals.hint.pending_payment';
      case 'refunded':
      case 'disputed':
      case 'cancelled':
        return 'deals.hint.${d.status}';
      case kDealCompleted:
        return widget.role.isBuyer ? 'deals.hint.completed' : null;
      case kDealPaid:
        return a.startFulfilment ? null : 'deals.hint.wait_supplier';
      case kDealInFulfilment:
        return a.confirmReceipt ? 'deals.hint.wait_delivery' : null;
    }
    return null;
  }

  Widget _button(
    String key,
    String label,
    IconData icon,
    String name,
    VoidCallback onPressed,
  ) =>
      Padding(
        padding: const EdgeInsets.only(top: AppSpacing.sm),
        child: SizedBox(
          width: double.infinity,
          child: PrimaryButton(
            key: Key(key),
            label: label,
            icon: icon,
            loading: _busy == name,
            onPressed: _busy == null ? onPressed : null,
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final deal = widget.deal;
    final actions = dealActionsFor(deal, widget.role);
    final hint = _hintKey(deal, actions);
    final repo = ref.watch(dealsRepositoryProvider);
    final events = ref.watch(dealEventsProvider(deal.id));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: context.tr('deals.section.title')),
        DealStatusChips(deal: deal),
        if (deal.deliveredAt != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.sm),
            child: Text(
              context.tr('deals.delivered_at', {'d': dealDateTimeLabel(deal.deliveredAt!)}),
              style: const TextStyle(color: AppColors.textSecondary),
            ),
          ),
        if (deal.completedAt != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
              context.tr('deals.completed_at', {'d': dealDateTimeLabel(deal.completedAt!)}),
              style: const TextStyle(color: AppColors.textSecondary),
            ),
          ),
        if (hint != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.sm),
            child: Text(
              context.tr(hint),
              style: const TextStyle(color: AppColors.textSecondary),
            ),
          ),
        if (repo is MockDealsRepository && deal.status == kDealPendingPayment)
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: TextButton(
              key: const Key('deal_simulate_paid'),
              onPressed: _busy == null
                  ? () => _run('simulate_paid', (_) => repo.simulatePayment(deal.id))
                  : null,
              child: Text(
                context.tr('deals.action.simulate_paid'),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
        if (actions.startFulfilment)
          _button('deal_start_fulfilment', context.tr('deals.action.start'),
              Icons.play_circle_outline, 'start', () {
            _run('start', (r) => r.startFulfilment(deal.id));
          }),
        if (actions.markDelivered)
          _button('deal_mark_delivered', context.tr('deals.action.delivered'),
              Icons.local_shipping_outlined, 'delivered', () {
            _run('delivered', (r) => r.markDelivered(deal.id));
          }),
        if (actions.confirmReceipt)
          _button('deal_confirm_receipt', context.tr('deals.action.confirm'),
              Icons.task_alt, 'confirm', _confirm),
        const SizedBox(height: AppSpacing.lg),
        SectionHeader(title: context.tr('deals.events.title')),
        events.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpacing.lg),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (e, _) => ErrorState(
            message: context.tr(dealErrorKey(e)),
            onRetry: () => ref.invalidate(dealEventsProvider(deal.id)),
          ),
          data: (list) => DealEventsTimeline(events: list.items),
        ),
      ],
    );
  }
}
