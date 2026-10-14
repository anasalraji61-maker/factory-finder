import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/freight/screens/freight_home_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// "Get freight quotes" button for the landed-cost results screen: opens the
/// request form prefilled from [quote] (and the calculator inputs, if known).
class FreightQuoteButton extends ConsumerWidget {
  const FreightQuoteButton({super.key, required this.quote});

  final LandedCostQuote quote;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: OutlinedButton.icon(
        key: const ValueKey<String>('freight_get_quotes'),
        style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
        onPressed: () {
          ref.read(freightPrefillProvider.notifier).state = FreightPrefill.fromLandedCost(
            quote,
            inputs: ref.read(lastQuoteRequestProvider),
          );
          context.push('$kFreightBase/new');
        },
        icon: const Icon(Icons.local_shipping_outlined),
        label: Text(context.tr('freight.get_quotes')),
      ),
    );
  }
}
