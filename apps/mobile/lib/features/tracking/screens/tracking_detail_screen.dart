import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/tracking/screens/tracking_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class TrackingDetailScreen extends ConsumerStatefulWidget {
  const TrackingDetailScreen({super.key, required this.shipmentId});
  final String shipmentId;

  @override
  ConsumerState<TrackingDetailScreen> createState() => _TrackingDetailScreenState();
}

class _TrackingDetailScreenState extends ConsumerState<TrackingDetailScreen> {
  bool _refreshing = false;

  Future<void> _refresh() async {
    setState(() => _refreshing = true);
    try {
      await ref.read(trackingRepositoryProvider).refresh(widget.shipmentId);
      if (!mounted) return;
      ref.invalidate(shipmentProvider(widget.shipmentId));
      ref.invalidate(shipmentsProvider);
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(context.tr('tracking.refreshed'))));
      }
    } catch (_) {
      // Keep the current data; the user can retry.
    }
    if (mounted) setState(() => _refreshing = false);
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(shipmentProvider(widget.shipmentId));
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
        ],
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorState(
          message: e.toString(),
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
            if (s.delayed) ...[
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
            if (s.events.isEmpty)
              Padding(
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Text(context.tr('tracking.no_events')),
              )
            else
              for (var i = 0; i < s.events.length; i++)
                _TimelineTile(
                  event: s.events[i],
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
              Icon(Icons.directions_boat_outlined, color: color),
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
                style: theme.textTheme.bodyMedium),
          if (s.eta != null)
            Text('${context.tr('tracking.eta')}: ${dateLabel(s.eta!)}',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.w800)),
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
  const _TimelineTile({required this.event, required this.isFirst, required this.isLast});
  final TrackingEvent event;
  final bool isFirst;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = isFirst ? statusColor(event.status) : AppColors.textSecondary;
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
                  Text(event.description,
                      style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: isFirst ? FontWeight.w800 : FontWeight.w600)),
                  if (event.location.isNotEmpty)
                    Text(event.location,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: AppColors.textSecondary)),
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
