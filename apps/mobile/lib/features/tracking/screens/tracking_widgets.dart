import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/tracking/data/tracking_models.dart';
import 'package:flutter/material.dart';

String statusKey(ShipmentStatus s) => 'tracking.status.${s.wire}';

String typeKey(ReferenceType t) => 'tracking.type.${t.wire}';

String _two(int n) => n.toString().padLeft(2, '0');

String dateLabel(DateTime d) => '${d.year}/${_two(d.month)}/${_two(d.day)}';

String dateTimeLabel(DateTime d) => '${dateLabel(d)} ${_two(d.hour)}:${_two(d.minute)}';

Color statusColor(ShipmentStatus s) {
  switch (s) {
    case ShipmentStatus.delivered:
    case ShipmentStatus.released:
      return AppColors.success;
    case ShipmentStatus.customsHold:
      return AppColors.warning;
    case ShipmentStatus.unknown:
      return AppColors.textSecondary;
    default:
      return AppColors.primary;
  }
}

IconData statusIcon(ShipmentStatus s) {
  switch (s) {
    case ShipmentStatus.booked:
      return Icons.event_available_outlined;
    case ShipmentStatus.gateIn:
      return Icons.login;
    case ShipmentStatus.loaded:
      return Icons.upload_outlined;
    case ShipmentStatus.departed:
      return Icons.directions_boat_outlined;
    case ShipmentStatus.transshipment:
      return Icons.swap_horiz;
    case ShipmentStatus.arrived:
      return Icons.anchor;
    case ShipmentStatus.discharged:
      return Icons.download_outlined;
    case ShipmentStatus.customsHold:
      return Icons.gpp_maybe_outlined;
    case ShipmentStatus.released:
      return Icons.verified_outlined;
    case ShipmentStatus.outForDelivery:
      return Icons.local_shipping_outlined;
    case ShipmentStatus.delivered:
      return Icons.check_circle_outline;
    case ShipmentStatus.unknown:
      return Icons.help_outline;
  }
}

class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.status});
  final ShipmentStatus status;

  @override
  Widget build(BuildContext context) {
    final color = statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        context.tr(statusKey(status)),
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w800),
      ),
    );
  }
}

/// i18n key for a contract `warning` such as `provider_unavailable:rate_limited`.
String trackingWarningKey(String warning) {
  final i = warning.indexOf(':');
  final reason = i >= 0 ? warning.substring(i + 1) : '';
  const known = <String>{
    'kill_switch',
    'not_configured',
    'rate_limited',
    'upstream_error',
    'timeout',
    'blocked',
    'bad_payload',
  };
  return known.contains(reason) ? 'tracking.warning.$reason' : 'tracking.warning.generic';
}

/// Amber banner: icon, bold title and an optional message (overflow-safe).
class TrackingBanner extends StatelessWidget {
  const TrackingBanner({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.color = AppColors.warning,
  });

  final IconData icon;
  final String title;
  final String? message;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w800),
                ),
                if (message != null)
                  Text(
                    message!,
                    maxLines: 4,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// "Delayed by N h" banner with the original ETA, shown when `delayed`.
class DelayBanner extends StatelessWidget {
  const DelayBanner({super.key, required this.shipment});

  final Shipment shipment;

  @override
  Widget build(BuildContext context) {
    final s = shipment;
    final h = s.delayHours;
    String? by;
    if (h != null && h > 0) {
      by = h >= 48
          ? context.tr('tracking.delayed_days', {'d': '${(h / 24).round()}'})
          : context.tr('tracking.delayed_by', {'h': '$h'});
    }
    final lines = <String>[
      if (by != null) by,
      if (s.initialEta != null)
        context.tr('tracking.initial_eta', {'d': dateLabel(s.initialEta!)}),
    ];
    return TrackingBanner(
      icon: Icons.schedule,
      title: context.tr('tracking.delayed'),
      message: lines.isEmpty ? null : lines.join('\n'),
    );
  }
}

/// Milestones (gate in, loaded, ...) that the provider reported, in order.
class MilestonesWrap extends StatelessWidget {
  const MilestonesWrap({super.key, required this.milestones});

  final Map<String, DateTime> milestones;

  @override
  Widget build(BuildContext context) {
    final keys = <String>[
      for (final k in kMilestoneOrder)
        if (milestones.containsKey(k)) k,
      ...milestones.keys.where((k) => !kMilestoneOrder.contains(k)),
    ];
    if (keys.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.sm,
      children: [
        for (final k in keys)
          Container(
            key: Key('milestone_$k'),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.primary.withOpacity(0.08),
              borderRadius: BorderRadius.circular(10),
            ),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 200),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    () {
                      final key = 'tracking.milestone.$k';
                      final t = context.tr(key);
                      return t == key ? k : t;
                    }(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w800),
                  ),
                  Text(
                    dateTimeLabel(milestones[k]!),
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
    );
  }
}
