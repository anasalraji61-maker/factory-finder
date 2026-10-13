import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class LogisticsScreen extends ConsumerWidget {
  const LogisticsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final last = ref.watch(lastQuoteProvider);
    final theme = Theme.of(context);
    final tools = <(IconData, String, String?)>[
      (Icons.currency_exchange, 'logistics.tool.fx', '/logistics/fx'),
      (Icons.directions_boat_outlined, 'logistics.tool.carriers', '/logistics/carriers'),
      (Icons.track_changes, 'logistics.tool.tracking', '/logistics/tracking'),
    ];

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('logistics.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.xl),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [AppColors.primary, AppColors.primaryDark],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(AppRadius.lg),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.local_shipping_rounded, color: AppColors.accent, size: 36),
                const SizedBox(height: AppSpacing.md),
                Text(
                  context.tr('logistics.hero_title'),
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  context.tr('logistics.hero_msg'),
                  style: const TextStyle(color: Colors.white70, height: 1.5),
                ),
                const SizedBox(height: AppSpacing.lg),
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.black,
                    minimumSize: const Size(0, 48),
                  ),
                  onPressed: () => context.push('/logistics/calculator'),
                  icon: const Icon(Icons.calculate_outlined),
                  label: Text(
                    context.tr('logistics.open_calc'),
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
              ],
            ),
          ),
          if (last != null) ...[
            const SizedBox(height: AppSpacing.lg),
            SectionHeader(title: context.tr('logistics.last_quote')),
            AppCard(
              onTap: () => context.push('/logistics/results'),
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                  CountryFlag(countryCode: last.origin?.countryCode ?? 'CN', size: 22),
                  const Icon(Icons.arrow_right_alt, size: 20),
                  CountryFlag(countryCode: last.destination?.countryCode ?? 'IQ', size: 22),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: last.options.isEmpty
                        ? Text(context.tr('logistics.results.no_options'))
                        : MoneyText.range(
                            last.options
                                .firstWhere(
                                  (o) => o.recommended,
                                  orElse: () => last.options.first,
                                )
                                .total,
                          ),
                  ),
                  Text(
                    context.tr('logistics.view'),
                    style: TextStyle(color: theme.colorScheme.primary),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: AppSpacing.lg),
          SectionHeader(title: context.tr('logistics.tools')),
          for (final tool in tools)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: AppCard(
                onTap: tool.$3 == null ? null : () => context.push(tool.$3!),
                child: Row(
                  children: [
                    Icon(tool.$1, color: AppColors.textSecondary),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(child: Text(context.tr(tool.$2))),
                    if (tool.$3 == null)
                      Text(
                        context.tr('common.coming_soon'),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      )
                    else
                      const Icon(Icons.chevron_left,
                          color: AppColors.textSecondary),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
