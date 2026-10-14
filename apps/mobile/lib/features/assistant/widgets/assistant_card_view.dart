import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';
import 'package:flutter/material.dart';

Color assistantSeverityColor(String severity) {
  switch (severity) {
    case 'ok':
      return AppColors.success;
    case 'warning':
      return AppColors.warning;
    case 'error':
      return AppColors.danger;
    default:
      return AppColors.primary;
  }
}

IconData assistantCardIcon(String type) {
  switch (type) {
    case 'shipment_status':
      return Icons.local_shipping_outlined;
    case 'deal_status':
      return Icons.handshake_outlined;
    case 'listing_comparison':
      return Icons.compare_arrows_rounded;
    case 'hs_code':
      return Icons.qr_code_2_rounded;
    case 'notice':
      return Icons.info_outline_rounded;
    default:
      return Icons.article_outlined;
  }
}

/// Renders one assistant card in the current locale. Unknown card types are
/// shown from their title and rows. [onNavigate] receives an existing route.
class AssistantCardView extends StatelessWidget {
  const AssistantCardView({super.key, required this.card, this.onNavigate});

  final AssistantCard card;
  final void Function(String route)? onNavigate;

  @override
  Widget build(BuildContext context) {
    final lang = Localizations.localeOf(context).languageCode;
    final theme = Theme.of(context);
    final color = assistantSeverityColor(card.severity);
    final actions = card.actions;
    final footnote = card.footnoteFor(lang);
    final hasColumns = card.columns.isNotEmpty;
    final shipmentAction = card.type == 'shipment_status' && actions.isNotEmpty
        ? actions.first
        : null;

    return AppCard(
      padding: EdgeInsets.zero,
      onTap: shipmentAction == null || onNavigate == null
          ? null
          : () => onNavigate!(shipmentAction.route),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(AppRadius.md),
        child: Container(
        decoration: BoxDecoration(
          border: BorderDirectional(start: BorderSide(color: color, width: 4)),
        ),
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(assistantCardIcon(card.type), color: color, size: 22),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    card.titleFor(lang),
                    style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ),
              ],
            ),
            if (hasColumns) ...[
              const SizedBox(height: AppSpacing.sm),
              _CellsRow(
                label: '',
                cells: [for (final c in card.columns) c.label(lang)],
                bold: true,
              ),
            ],
            const SizedBox(height: AppSpacing.xs),
            for (final r in card.rows)
              if (r.values != null)
                _CellsRow(
                  label: r.labelFor(lang),
                  cells: r.values!,
                  highlight: r.highlight,
                )
              else
                _ValueRow(
                  label: r.labelFor(lang),
                  value: r.valueFor(lang) ?? context.tr('assistant.empty_value'),
                ),
            if (footnote != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                footnote,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: AppColors.textSecondary, height: 1.3),
              ),
            ],
            if (actions.isNotEmpty && onNavigate != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final a in actions)
                    OutlinedButton(
                      onPressed: () => onNavigate!(a.route),
                      child: Text(context.tr(a.labelKey, a.args)),
                    ),
                ],
              ),
            ],
          ],
        ),
        ),
      ),
    );
  }
}

class _ValueRow extends StatelessWidget {
  const _ValueRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 2,
            child: Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            flex: 3,
            child: Text(value, style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }
}

/// Comparison row / column header: a label then one equally wide cell per column.
class _CellsRow extends StatelessWidget {
  const _CellsRow({
    required this.label,
    required this.cells,
    this.highlight,
    this.bold = false,
  });

  final String label;
  final List<String> cells;
  final int? highlight;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 2,
            child: Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
          ),
          for (var i = 0; i < cells.length; i++) ...[
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              flex: 3,
              child: Text(
                cells[i],
                style: TextStyle(
                  fontWeight: bold || highlight == i ? FontWeight.w800 : FontWeight.w500,
                  color: highlight == i ? AppColors.success : null,
                  fontSize: bold ? 12 : null,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
