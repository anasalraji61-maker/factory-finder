import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/api/me_refresh.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:factory_finder/features/settings/session_cleanup.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

const List<String> kDisplayCurrencies = [
  'USD', 'EUR', 'CNY', 'IQD', 'TRY', 'AED', 'SAR', 'GBP',
];

/// Login / register buttons: side by side, stacked at large text sizes.
class _AuthButtons extends StatelessWidget {
  const _AuthButtons({
    required this.big,
    required this.login,
    required this.register,
  });

  final bool big;
  final Widget login;
  final Widget register;

  @override
  Widget build(BuildContext context) {
    if (big) {
      return Column(
        children: [
          SizedBox(width: double.infinity, child: login),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(width: double.infinity, child: register),
        ],
      );
    }
    return Row(
      children: [
        Expanded(child: login),
        const SizedBox(width: AppSpacing.md),
        Expanded(child: register),
      ],
    );
  }
}

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider);
    final currency = ref.watch(displayCurrencyProvider);
    final destination = ref.watch(destinationProvider);
    final me = ref.watch(authProvider);
    final serverUrl = ref.watch(serverUrlProvider);
    final role = ref.watch(userRoleProvider);
    final showMyProducts =
        role == UserRole.supplier || me?.supplierClaimStatus == 'verified';

    final claimRevoked = ref.watch(supplierClaimRevokedNoticeProvider) && me != null;

    return MeRefreshOnOpen(
      child: Scaffold(
      appBar: AppBar(title: Text(context.tr('profile.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          if (claimRevoked) ...[
            AppCard(
              key: const ValueKey('profile-claim-revoked'),
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.gpp_maybe_outlined, color: AppColors.warning),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Text(
                          context.tr('claim.revoked_title'),
                          style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(context.tr('claim.revoked_msg')),
                  const SizedBox(height: AppSpacing.md),
                  Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.sm,
                    children: [
                      FilledButton(
                        key: const ValueKey('profile-claim-revoked-apply'),
                        onPressed: () {
                          ref.read(supplierClaimRevokedNoticeProvider.notifier).state = false;
                          context.push('/supplier-claim');
                        },
                        child: Text(context.tr('claim.revoked_apply')),
                      ),
                      TextButton(
                        key: const ValueKey('profile-claim-revoked-dismiss'),
                        onPressed: () =>
                            ref.read(supplierClaimRevokedNoticeProvider.notifier).state = false,
                        child: Text(context.tr('claim.revoked_dismiss')),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
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
            _AuthButtons(
              big: MediaQuery.textScalerOf(context).scale(14) / 14 > 1.3,
              login: PrimaryButton(
                label: context.tr('auth.login'),
                icon: Icons.login,
                onPressed: () => context.push('/login'),
              ),
              register: OutlinedButton(
                style: OutlinedButton.styleFrom(minimumSize: const Size(64, 50)),
                onPressed: () => context.push('/register'),
                child: Text(context.tr('auth.register')),
              ),
            )
          else
            OutlinedButton.icon(
              onPressed: () {
                ref.read(authProvider.notifier).logout();
                clearSignedOutUserStateOf(ref);
              },
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
                ListTile(
                  key: const ValueKey('profile-settings'),
                  leading: const Icon(Icons.settings_outlined),
                  title: Text(context.tr('settings.tile')),
                  subtitle: Text(context.tr('settings.tile_sub')),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push('/settings'),
                ),
                if (serverUrlOverrideAllowed()) ...[
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
                ],
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.storefront_outlined),
                  title: Text(context.tr('claim.tile_title')),
                  subtitle: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(me?.supplierId == null
                        ? context.tr('claim.not_linked')
                        : me!.supplierClaimStatus == 'pending'
                            ? context.tr('claim.pending_short', {'id': verbatim(me.supplierId!)})
                            : me.supplierId!),
                  ),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push('/supplier-claim'),
                ),
                const Divider(height: 1),
                if (showMyProducts) ...[
                  ListTile(
                    key: const ValueKey('profile-my-products'),
                    leading: const Icon(Icons.inventory_2_outlined),
                    title: Text(context.tr('myp.tile')),
                    subtitle: Text(context.tr('myp.tile_sub')),
                    trailing: const Icon(Icons.chevron_right, size: 20),
                    onTap: () => context.push('/my-products'),
                  ),
                  const Divider(height: 1),
                  ListTile(
                    key: const ValueKey('profile-verification'),
                    leading: const Icon(Icons.domain_verification),
                    title: Text(context.tr('ver.tile')),
                    subtitle: Text(context.tr('ver.tile_sub')),
                    trailing: const Icon(Icons.chevron_right, size: 20),
                    onTap: () => context.push('/verification'),
                  ),
                  const Divider(height: 1),
                ],
                ListTile(
                  leading: const Icon(Icons.bookmark_border),
                  title: Text(context.tr('profile.watchlist')),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push('/watchlist'),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.assignment_turned_in_outlined),
                  title: Text(context.tr('deals.list.tile')),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push('/deals'),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.notifications_none),
                  title: Text(context.tr('watch.alerts_title')),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push('/alerts'),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.tune),
                  title: Text(context.tr('notifyprefs.tile')),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.push('/notification-prefs'),
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
    // Not disposed here: the dialog route is still animating out and its
    // TextField would touch a disposed controller. It holds no resources.
    if (result != null && result.isNotEmpty) {
      ref.read(serverUrlProvider.notifier).state =
          result.endsWith('/') ? result.substring(0, result.length - 1) : result;
    }
  }
}
