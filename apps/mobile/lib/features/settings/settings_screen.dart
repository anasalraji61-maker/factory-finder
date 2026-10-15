import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/reco/widgets/recent_settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// Currencies offered as the default display currency (IQD first: default for Iraq).
const List<String> kSettingsCurrencies = [
  'IQD', 'USD', 'EUR', 'AED', 'TRY', 'SAR', 'CNY', 'GBP',
];

/// Quick city presets per destination country (stored as the English name).
const Map<String, List<String>> kCityPresets = {
  'IQ': ['Baghdad', 'Basra', 'Erbil', 'Sulaymaniyah', 'Najaf', 'Mosul', 'Kirkuk'],
  'TR': ['Istanbul', 'Ankara', 'Mersin'],
  'AE': ['Dubai', 'Abu Dhabi', 'Sharjah'],
  'SA': ['Riyadh', 'Jeddah'],
  'JO': ['Amman'],
  'EG': ['Cairo'],
};

String cityLabel(BuildContext context, String city) => translateCity(context, city);

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider);
    final themeMode = ref.watch(themeModeProvider);
    final currency = ref.watch(displayCurrencyProvider);
    final destination = ref.watch(destinationProvider);
    final digits = ref.watch(digitStyleProvider);
    final signedIn = ref.watch(authProvider) != null;
    final cities = kCityPresets[destination?.countryCode] ?? const <String>[];

    return Scaffold(
      appBar: AppBar(title: Text(context.tr('settings.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          _Section(
            title: context.tr('settings.language'),
            child: _Choices<String>(
              value: locale.languageCode,
              options: [
                ('ar', context.tr('profile.language_ar')),
                ('en', context.tr('profile.language_en')),
              ],
              keyPrefix: 'settings-lang-',
              onChanged: (v) => ref.read(localeProvider.notifier).state = Locale(v),
            ),
          ),
          _Section(
            title: context.tr('settings.theme'),
            child: _Choices<ThemeMode>(
              value: themeMode,
              options: [
                (ThemeMode.light, context.tr('settings.theme.light')),
                (ThemeMode.dark, context.tr('settings.theme.dark')),
                (ThemeMode.system, context.tr('settings.theme.system')),
              ],
              keyPrefix: 'settings-theme-',
              onChanged: (v) => ref.read(themeModeProvider.notifier).state = v,
            ),
          ),
          _Section(
            title: context.tr('settings.currency'),
            hint: context.tr('settings.currency_hint'),
            child: _Choices<String>(
              value: currency,
              options: [
                for (final c in kSettingsCurrencies)
                  (c, '$c · ${context.tr('currency.$c')}'),
              ],
              keyPrefix: 'settings-currency-',
              onChanged: (v) =>
                  ref.read(displayCurrencyProvider.notifier).state = v,
            ),
          ),
          _Section(
            title: context.tr('settings.destination'),
            hint: context.tr('settings.destination_hint'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ListTile(
                  key: const ValueKey('settings-destination'),
                  contentPadding: EdgeInsets.zero,
                  minVerticalPadding: 8,
                  leading: destination == null
                      ? const Icon(Icons.place_outlined)
                      : CountryFlag(countryCode: destination.countryCode, size: 24),
                  title: Text(locationLabel(context, destination)),
                  subtitle: Text(context.tr('settings.destination_country')),
                  trailing: const Icon(Icons.edit_outlined),
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
                if (cities.isNotEmpty) ...[
                  Text(
                    context.tr('settings.city'),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  _Choices<String>(
                    value: destination?.city ?? '',
                    options: [for (final c in cities) (c, cityLabel(context, c))],
                    keyPrefix: 'settings-city-',
                    onChanged: (v) => ref.read(destinationProvider.notifier).state =
                        Location(
                      countryCode: destination?.countryCode ?? 'IQ',
                      city: v,
                    ),
                  ),
                ],
              ],
            ),
          ),
          _Section(
            title: context.tr('settings.digits'),
            child: _Choices<DigitStyle>(
              value: digits,
              options: [
                (DigitStyle.western, context.tr('settings.digits.western')),
                (DigitStyle.arabicIndic, context.tr('settings.digits.arabic')),
              ],
              keyPrefix: 'settings-digits-',
              onChanged: (v) => ref.read(digitStyleProvider.notifier).state = v,
            ),
          ),
          const RecentlyViewedSettings(),
          if (signedIn) ...[
            AppCard(
              padding: EdgeInsets.zero,
              child: ListTile(
                key: const ValueKey<String>('settings-change-password'),
                leading: const Icon(Icons.lock_outline),
                title: Text(context.tr('auth.change.title')),
                subtitle: Text(context.tr('auth.change.tile_sub')),
                trailing: const Icon(Icons.chevron_right, size: 20),
                onTap: () => context.push('/settings/change-password'),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            AppCard(
              padding: EdgeInsets.zero,
              child: ListTile(
                key: const ValueKey<String>('settings-logout-all'),
                leading: const Icon(Icons.devices_other_outlined),
                title: Text(context.tr('auth.logout_all.title')),
                subtitle: Text(context.tr('auth.logout_all.sub')),
                onTap: () => _confirmLogoutAll(context, ref),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          AppCard(
            padding: EdgeInsets.zero,
            child: ListTile(
              key: const ValueKey<String>('settings-privacy'),
              leading: const Icon(Icons.privacy_tip_outlined),
              title: Text(context.tr('privacy.tile')),
              subtitle: Text(context.tr('privacy.tile_sub')),
              trailing: const Icon(Icons.chevron_right, size: 20),
              onTap: () => context.push('/settings/privacy'),
            ),
          ),
        ],
      ),
    );
  }
}

Future<void> _confirmLogoutAll(BuildContext context, WidgetRef ref) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(ctx.tr('auth.logout_all.title')),
      content: Text(ctx.tr('auth.logout_all.body')),
      actions: [
        TextButton(
          key: const ValueKey<String>('logout-all-cancel'),
          onPressed: () => Navigator.of(ctx).pop(false),
          child: Text(ctx.tr('auth.logout_all.cancel')),
        ),
        TextButton(
          key: const ValueKey<String>('logout-all-confirm'),
          onPressed: () => Navigator.of(ctx).pop(true),
          child: Text(ctx.tr('auth.logout_all.confirm')),
        ),
      ],
    ),
  );
  if (confirmed != true || !context.mounted) return;
  final messenger = ScaffoldMessenger.of(context);
  final failed = context.tr('auth.logout_all.failed');
  try {
    await ref.read(authProvider.notifier).logoutAll();
  } catch (_) {
    messenger.showSnackBar(SnackBar(content: Text(failed)));
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child, this.hint});

  final String title;
  final String? hint;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: AppCard(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: SizedBox(
          width: double.infinity,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                header: true,
                child: Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              if (hint != null) ...[
                const SizedBox(height: 2),
                Text(
                  hint!,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.secondaryOf(context)),
                ),
              ],
              const SizedBox(height: AppSpacing.sm),
              child,
            ],
          ),
        ),
      ),
    );
  }
}

/// Wrapping single-choice chips (wraps instead of overflowing at large text).
class _Choices<T> extends StatelessWidget {
  const _Choices({
    required this.value,
    required this.options,
    required this.onChanged,
    required this.keyPrefix,
  });

  final T value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;
  final String keyPrefix;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppSpacing.sm,
      runSpacing: AppSpacing.sm,
      children: [
        for (final o in options)
          ChoiceChip(
            key: ValueKey('$keyPrefix${o.$1}'),
            label: Text(o.$2),
            selected: value == o.$1,
            onSelected: (_) => onChanged(o.$1),
          ),
      ],
    );
  }
}
