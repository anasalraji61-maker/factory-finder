import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Minimum gap between two manual refreshes of the same screen.
const Duration kTrackingRefreshCooldown = Duration(seconds: 20);

class TrackingDetailScreen extends ConsumerStatefulWidget {
  const TrackingDetailScreen({super.key, required this.shipmentId});
  final String shipmentId;

  @override
  ConsumerState<TrackingDetailScreen> createState() => _TrackingDetailScreenState();
}

class _TrackingDetailScreenState extends ConsumerState<TrackingDetailScreen> {
  bool _refreshing = false;
  bool _deleting = false;
  DateTime? _lastRefresh;

  void _snack(String text) {
    ScaffoldMessenger.of(context)
      ..removeCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _refresh() async {
    if (_refreshing || _deleting) return;
    final last = _lastRefresh;
    if (last != null && DateTime.now().difference(last) < kTrackingRefreshCooldown) {
      _snack(context.tr('tracking.refresh_wait'));
      return;
    }
    setState(() => _refreshing = true);
    String message;
    try {
      await ref.read(trackingRepositoryProvider).refresh(widget.shipmentId);
      _lastRefresh = DateTime.now();
      if (!mounted) return;
      ref.invalidate(shipmentProvider(widget.shipmentId));
      ref.invalidate(shipmentsProvider);
      message = context.tr('tracking.refreshed');
    } catch (e) {
      // Keep the current data; tell the user and let them retry.
      if (!mounted) return;
      message = '${context.tr('tracking.refresh_failed')}\n${localizedError(context, e)}';
    }
    if (!mounted) return;
    setState(() => _refreshing = false);
    _snack(message);
  }

  Future<void> _confirmDelete(Shipment s) async {
    if (_deleting || _refreshing) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('tracking.delete_title')),
        content: Text(ctx.tr('tracking.delete_msg', {'r': s.reference})),
        actions: [
          TextButton(
            key: const Key('tracking_delete_cancel'),
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(ctx.tr('common.cancel')),
          ),
          TextButton(
            key: const Key('tracking_delete_confirm'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(ctx.tr('tracking.delete_confirm')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _deleting = true);
    try {
      await ref.read(trackingRepositoryProvider).delete(s.id);
    } catch (_) {
      if (!mounted) return;
      setState(() => _deleting = false);
      _snack(context.tr('tracking.delete_failed'));
      return;
    }
    if (!mounted) return;
    ref.invalidate(shipmentsProvider);
    _snack(context.tr('tracking.deleted'));
    final nav = Navigator.of(context);
    if (nav.canPop()) {
      nav.pop();
    } else {
      // Opened from a deep link: there is nothing underneath to return to.
      GoRouter.maybeOf(context)?.go('/logistics/tracking');
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(shipmentProvider(widget.shipmentId));
    final loaded = async.valueOrNull;
    return Scaffold(
      appBar: AppBar(
        title: Text(context.tr('tracking.detail')),
        actions: [
          _refreshing
              ? const Padding(
                  padding: EdgeInsets.all(14),
                  child: SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2.5),
                  ),
                )
              : IconButton(
                  tooltip: context.tr('tracking.refresh'),
                  icon: const Icon(Icons.refresh),
                  onPressed: _refresh,
                ),
          if (loaded != null)
            IconButton(
              key: const Key('tracking_delete'),
              tooltip: context.tr('tracking.delete'),
              icon: const Icon(Icons.delete_outline),
              onPressed: _deleting ? null : () => _confirmDelete(loaded),
            ),
        ],
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorState(
          error: e,
          onRetry: () => ref.invalidate(shipmentProvider(widget.shipmentId)),
        ),
        data: (s) => ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            if (s.warning != null) ...[
              TrackingBanner(
                key: const Key('tracking_warning'),
                icon: Icons.warning_amber_rounded,
                title: context.tr('tracking.warning.title'),
                message: context.tr(trackingWarningKey(s.warning!)),
              ),
              const SizedBox(height: AppSpacing.md),
            ],
            if (s.delayed && s.status != ShipmentStatus.delivered) ...[
              DelayBanner(key: const Key('tracking_delay'), shipment: s),
              const SizedBox(height: AppSpacing.md),
            ],
            _Header(shipment: s),
            if (s.milestones.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.lg),
              SectionHeader(title: context.tr('tracking.milestones')),
              MilestonesWrap(milestones: s.milestones),
            ],
            const SizedBox(height: AppSpacing.lg),
            SectionHeader(title: context.tr('tracking.timeline')),
            if (s.events.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: Text(
                  '${context.tr('tracking.event_time_hint')} (${utcOffsetLabel(s.events.first.time)})',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ),
            if (s.events.isEmpty)
              Padding(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Text(context.tr('tracking.no_events')),
              )
            else
              for (var i = 0; i < s.events.length; i++)
                _TimelineTile(
                  event: s.events[i],
                  index: i,
                  isFirst: i == 0,
                  isLast: i == s.events.length - 1,
                ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.shipment});
  final Shipment shipment;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = shipment;
    final color = statusColor(s.status);
    final deliveredAt =
        s.status == ShipmentStatus.delivered ? s.milestones['delivered'] : null;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Directionality(
                  textDirection: TextDirection.ltr,
                  child: Text(
                    s.reference,
                    style: theme.textTheme.titleLarge
                        ?.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.5),
                  ),
                ),
              ),
              StatusChip(status: s.status),
            ],
          ),
          Text(
            '${context.tr(typeKey(s.referenceType))}'
            '${s.carrier == null ? '' : ' · ${s.carrier}'}',
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.lg),
          Row(
            children: [
              Expanded(child: _Endpoint(label: s.origin, icon: Icons.circle_outlined)),
              Icon(
                  s.referenceType == ReferenceType.awb
                      ? Icons.flight
                      : Icons.directions_boat_outlined,
                  color: color),
              Expanded(
                child: _Endpoint(
                  label: s.destination,
                  icon: Icons.location_on_outlined,
                  end: true,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: s.progressValue,
              minHeight: 10,
              color: color,
              backgroundColor: AppColors.border,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          if (s.vesselName != null)
            Text('${context.tr('tracking.vessel')}: ${s.vesselName}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodyMedium),
          if (deliveredAt != null)
            Text('${context.tr('tracking.delivered_on')}: ${dateTimeLabel(deliveredAt)}',
                key: const Key('tracking_delivered_on'),
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.w800))
          else if (s.eta != null)
            Text('${context.tr('tracking.eta_label')}: ${dateLabel(s.eta!)}',
                key: const Key('tracking_eta'),
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.w800)),
          if (deliveredAt == null &&
              s.eta != null &&
              s.initialEta != null &&
              dateLabel(s.initialEta!) != dateLabel(s.eta!))
            Text(context.tr('tracking.initial_eta', {'d': dateLabel(s.initialEta!)}),
                key: const Key('tracking_initial_eta'),
                style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary)),
          if (s.updatedAt != null)
            Text('${context.tr('tracking.updated')}: ${dateTimeLabel(s.updatedAt!)}',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: AppColors.textSecondary)),
        ],
      ),
    );
  }
}

class _Endpoint extends StatelessWidget {
  const _Endpoint({required this.label, required this.icon, this.end = false});
  final String label;
  final IconData icon;
  final bool end;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: end ? CrossAxisAlignment.end : CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 18, color: AppColors.textSecondary),
        Text(
          label,
          textAlign: end ? TextAlign.end : TextAlign.start,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}

class _TimelineTile extends StatelessWidget {
  const _TimelineTile({
    required this.event,
    required this.index,
    required this.isFirst,
    required this.isLast,
  });
  final TrackingEvent event;
  final int index;
  final bool isFirst;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = (isFirst || event.isException)
        ? statusColor(event.status)
        : AppColors.textSecondary;
    // Never show an empty line: fall back to the (localized) status name.
    final title = event.description.trim().isEmpty
        ? context.tr(statusKey(event.status))
        : event.description;
    return IntrinsicHeight(
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
                    color: color.withOpacity(0.14),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(statusIcon(event.status), size: 18, color: color),
                ),
                if (!isLast)
                  Expanded(child: Container(width: 2, color: AppColors.border)),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      key: Key('timeline_title_$index'),
                      style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: isFirst ? FontWeight.w800 : FontWeight.w600)),
                  if (event.location.isNotEmpty)
                    Text(event.location,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: AppColors.textSecondary)),
                  if (event.transport.isNotEmpty)
                    Text(event.transport,
                        textDirection: TextDirection.ltr,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: AppColors.textSecondary)),
                  if (event.hasTime)
                    Text(dateTimeLabel(event.time),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: AppColors.textSecondary)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
