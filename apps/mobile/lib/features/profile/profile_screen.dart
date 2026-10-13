import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const List<String> kDisplayCurrencies = [
  'USD', 'EUR', 'CNY', 'IQD', 'TRY', 'AED', 'SAR',
];

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider);
    final currency = ref.watch(displayCurrencyProvider);
    final destination = ref.watch(destinationProvider);
    final themeMode = ref.watch(themeModeProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('profile.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.lg),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [AppColors.primary, AppColors.primaryDark],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(AppRadius.lg),
            ),
            child: Row(
              children: [
                const CircleAvatar(
                  radius: 28,
                  backgroundColor: AppColors.accent,
                  child: Icon(Icons.person, color: Colors.white, size: 30),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        context.tr('profile.mock_user'),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        context.tr('profile.mock_email'),
                        style: const TextStyle(color: Colors.white70),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.tr('profile.language'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: AppSpacing.sm),
                SegmentedButton<String>(
                  segments: [
                    ButtonSegment<String>(
                      value: 'ar',
                      label: Text(context.tr('profile.language_ar')),
                    ),
                    ButtonSegment<String>(
                      value: 'en',
                      label: Text(context.tr('profile.language_en')),
                    ),
                  ],
                  selected: {locale.languageCode},
                  onSelectionChanged: (s) => ref.read(localeProvider.notifier).state =
                      Locale(s.first),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text(
                  context.tr('profile.currency'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: AppSpacing.sm),
                Wrap(
                  spacing: AppSpacing.sm,
                  runSpacing: AppSpacing.sm,
                  children: [
                    for (final c in kDisplayCurrencies)
                      ChoiceChip(
                        label: Text(c),
                        selected: currency == c,
                        onSelected: (_) =>
                            ref.read(displayCurrencyProvider.notifier).state = c,
                      ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          AppCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: [
                ListTile(
                  leading: destination == null
                      ? const Icon(Icons.place_outlined)
                      : CountryFlag(countryCode: destination.countryCode, size: 24),
                  title: Text(context.tr('profile.destination')),
                  subtitle: Text(locationLabel(context, destination)),
                  trailing: const Icon(Icons.edit_outlined, size: 20),
                  onTap: () async {
                    final picked = await showLocationEditor(
                      context,
                      initial: destination ??
                          const Location(countryCode: 'IQ', city: 'Baghdad'),
                    );
                    if (picked != null) {
                      ref.read(destinationProvider.notifier).state = picked;
                    }
                  },
                ),
                const Divider(height: 1),
                SwitchListTile(
                  secondary: const Icon(Icons.dark_mode_outlined),
                  title: Text(context.tr('profile.theme')),
                  value: themeMode == ThemeMode.dark,
                  onChanged: (v) => ref.read(themeModeProvider.notifier).state =
                      v ? ThemeMode.dark : ThemeMode.light,
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.bookmark_border),
                  title: Text(context.tr('profile.watchlist')),
                  trailing: Text(
                    context.tr('common.coming_soon'),
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: AppColors.textSecondary),
                  ),
                  onTap: () => ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(context.tr('common.coming_soon'))),
                  ),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.info_outline),
                  title: Text(context.tr('profile.about')),
                  subtitle: Text(context.tr('profile.about_text')),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
