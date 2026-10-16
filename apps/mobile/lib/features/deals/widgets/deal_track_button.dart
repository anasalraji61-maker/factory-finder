import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/deals/deals_models.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/tracking/data/reference_validators.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/add_shipment_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Whether the deal is far enough along for a shipment to exist.
bool dealHasShipment(Deal deal) =>
    deal.status == kDealPaid ||
    deal.status == kDealInFulfilment ||
    deal.status == kDealCompleted;

/// "Track shipment" on the deal screen. With a reference on the deal it opens
/// that shipment (adding it first when it is not tracked yet); without one it
/// opens the add-reference form.
class DealTrackButton extends ConsumerStatefulWidget {
  const DealTrackButton({super.key, required this.deal});

  final Deal deal;

  @override
  ConsumerState<DealTrackButton> createState() => _DealTrackButtonState();
}

class _DealTrackButtonState extends ConsumerState<DealTrackButton> {
  bool _busy = false;

  Future<void> _open(String? reference) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      if (reference != null) {
        final wanted = normalizeReference(reference);
        try {
          final all = await ref.read(trackingRepositoryProvider).shipments();
          for (final s in all) {
            if (s.reference == wanted) {
              if (mounted) context.push('/logistics/tracking/${s.id}');
              return;
            }
          }
        } catch (_) {
          // Fall through to the add form, which reports its own errors.
        }
      }
      if (!mounted) return;
      final added = await showModalBottomSheet<Shipment>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (_) => AddShipmentSheet(initialReference: reference),
      );
      if (added != null && mounted) {
        ref.invalidate(shipmentsProvider);
        context.push('/logistics/tracking/${added.id}');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final events = ref.watch(dealEventsProvider(widget.deal.id)).valueOrNull;
    final reference = events == null ? null : dealTrackingReference(events);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (reference == null)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: Text(
                context.tr('deals.detail.track_hint'),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          OutlinedButton.icon(
            key: const Key('deal_track_shipment'),
            onPressed: _busy ? null : () => _open(reference),
            icon: const Icon(Icons.local_shipping_outlined, size: 18),
            label: Text(context.tr('deals.detail.track')),
          ),
        ],
      ),
    );
  }
}
