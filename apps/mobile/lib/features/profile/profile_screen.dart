import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
    final me = ref.watch(authProvider);
    final serverUrl = ref.watch(serverUrlProvider);

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
                        me?.name ?? context.tr('auth.guest'),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        me == null
                            ? context.tr('auth.guest_hint')
                            : (me.email ?? me.phone ?? ''),
                        style: const TextStyle(color: Colors.white70),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          if (me == null)
            Row(
              children: [
                Expanded(
                  child: PrimaryButton(
                    label: context.tr('auth.login'),
                    icon: Icons.login,
                    onPressed: () => context.push('/login'),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(minimumSize: const Size(64, 50)),
                    onPressed: () => context.push('/register'),
                    child: Text(context.tr('auth.register')),
                  ),
                ),
              ],
            )
          else
            OutlinedButton.icon(
              onPressed: () => ref.read(authProvider.notifier).logout(),
              icon: const Icon(Icons.logout),
              label: Text(context.tr('auth.logout')),
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
                  leading: const Icon(Icons.dns_outlined),
                  title: Text(context.tr('profile.server_url')),
                  subtitle: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(
                      kMockMode
                          ? context.tr('profile.server_mock')
                          : serverUrl,
                    ),
                  ),
                  trailing: const Icon(Icons.edit_outlined, size: 20),
                  onTap: () => _editServerUrl(context, ref, serverUrl),
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

  Future<void> _editServerUrl(
    BuildContext context,
    WidgetRef ref,
    String current,
  ) async {
    final controller = TextEditingController(text: current);
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(ctx.tr('profile.server_url')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: controller,
              keyboardType: TextInputType.url,
              textDirection: TextDirection.ltr,
              decoration: const InputDecoration(hintText: kDefaultBaseUrl),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              ctx.tr('profile.server_hint'),
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: Text(ctx.tr('common.cancel')),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(controller.text.trim()),
            child: Text(ctx.tr('common.save')),
          ),
        ],
      ),
    );
    controller.dispose();
    if (result != null && result.isNotEmpty) {
      ref.read(serverUrlProvider.notifier).state =
          result.endsWith('/') ? result.substring(0, result.length - 1) : result;
    }
  }
}
