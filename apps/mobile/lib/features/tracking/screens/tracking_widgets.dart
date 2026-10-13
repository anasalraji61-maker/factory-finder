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
