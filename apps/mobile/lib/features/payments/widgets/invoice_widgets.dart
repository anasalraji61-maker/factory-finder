import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/payments/payments_models.dart';
import 'package:factory_finder/features/requests/screens/requests_screen.dart'
    show StatusPill;
import 'package:flutter/material.dart';

Color invoiceStatusColor(InvoiceStatus s) {
  switch (s) {
    case InvoiceStatus.pending:
      return AppColors.textSecondary;
    case InvoiceStatus.awaitingPayment:
      return AppColors.warning;
    case InvoiceStatus.confirming:
      return AppColors.primary;
    case InvoiceStatus.paid:
      return AppColors.success;
    case InvoiceStatus.expired:
      return AppColors.textSecondary;
    case InvoiceStatus.failed:
      return AppColors.danger;
    case InvoiceStatus.refunded:
      return AppColors.accent;
    case InvoiceStatus.unknown:
      return AppColors.textSecondary;
  }
}

class InvoiceStatusChip extends StatelessWidget {
  const InvoiceStatusChip({super.key, required this.status});

  final InvoiceStatus status;

  @override
  Widget build(BuildContext context) => StatusPill(
        label: context.tr('pay.status.${status.json}'),
        color: invoiceStatusColor(status),
      );
}
