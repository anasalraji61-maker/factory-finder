import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// First-run flow: what the app does -> language/currency/destination -> role.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  static const int _pageCount = 3;

  final PageController _pages = PageController();
  int _page = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _finish({bool skipped = false}) {
    ref.read(onboardingCompletedProvider.notifier).state = true;
    final supplier = !skipped && ref.read(userRoleProvider) == UserRole.supplier;
    final router = GoRouter.of(context);
    router.go('/discover');
    if (supplier) router.push('/supplier-claim');
  }

  void _go(int delta) {
    _pages.animateToPage(
      _page + delta,
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
    );
  }

  Widget _scroll(List<Widget> children) => SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: children,
        ),
      );

  Widget _title(String text) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.lg),
        child: Text(
          text,
          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900),
        ),
      );

  Widget _label(String text) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.sm),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.w800)),
      );

  Widget _welcomePage(BuildContext context) {
    Widget point(String key) => Padding(
          padding: const EdgeInsets.only(top: AppSpacing.md),
          child: Row(
            children: [
              const Icon(Icons.check_circle, color: AppColors.accent),
              const SizedBox(width: AppSpacing.md),
              Expanded(child: Text(context.tr(key))),
            ],
          ),
        );
    return _scroll([
      const SizedBox(height: AppSpacing.lg),
      const Icon(Icons.factory_outlined, size: 64, color: AppColors.primary),
      const SizedBox(height: AppSpacing.lg),
      _title(context.tr('onb.p1.title')),
      Text(
        context.tr('onb.p1.body'),
        style: const TextStyle(color: AppColors.textSecondary, height: 1.5),
      ),
      point('onb.p1.point1'),
      point('onb.p1.point2'),
      point('onb.p1.point3'),
    ]);
  }

  Widget _prefsPage(BuildContext context) {
    final locale = ref.watch(localeProvider);
    final currency = ref.watch(displayCurrencyProvider);
    final destination = ref.watch(destinationProvider);
    return _scroll([
      _title(context.tr('onb.p2.title')),
      _label(context.tr('onb.language')),
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
        onSelectionChanged: (s) =>
            ref.read(localeProvider.notifier).state = Locale(s.first),
      ),
      _label(context.tr('onb.currency')),
      Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children: [
          for (final c in kOnboardingCurrencies)
            ChoiceChip(
              label: Text(c),
              selected: currency == c,
              onSelected: (_) =>
                  ref.read(displayCurrencyProvider.notifier).state = c,
            ),
        ],
      ),
      _label(context.tr('onb.destination')),
      AppCard(
        padding: EdgeInsets.zero,
        child: ListTile(
          leading: destination == null
              ? const Icon(Icons.place_outlined)
              : CountryFlag(countryCode: destination.countryCode, size: 24),
          title: Text(
            locationLabel(context, destination),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
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
      ),
    ]);
  }

  Widget _rolePage(BuildContext context) {
    final role = ref.watch(userRoleProvider);
    Widget card(UserRole r, IconData icon, String key) => Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.md),
          child: AppCard(
            padding: EdgeInsets.zero,
            child: ListTile(
              selected: role == r,
              leading: Icon(icon),
              title: Text(
                context.tr('onb.role.$key'),
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              subtitle: Text(context.tr('onb.role.${key}_desc')),
              trailing: role == r ? const Icon(Icons.check_circle) : null,
              onTap: () => ref.read(userRoleProvider.notifier).state = r,
            ),
          ),
        );
    return _scroll([
      _title(context.tr('onb.p3.title')),
      card(UserRole.buyer, Icons.shopping_bag_outlined, 'buyer'),
      card(UserRole.supplier, Icons.storefront_outlined, 'supplier'),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final last = _page == _pageCount - 1;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: TextButton(
                onPressed: () => _finish(skipped: true),
                child: Text(context.tr('onb.skip')),
              ),
            ),
            Expanded(
              child: PageView(
                controller: _pages,
                onPageChanged: (i) => setState(() => _page = i),
                children: [
                  _welcomePage(context),
                  _prefsPage(context),
                  _rolePage(context),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                  if (_page > 0)
                    TextButton(
                      onPressed: () => _go(-1),
                      child: Text(context.tr('onb.back')),
                    ),
                  Expanded(
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        for (var i = 0; i < _pageCount; i++)
                          Container(
                            width: 8,
                            height: 8,
                            margin: const EdgeInsets.symmetric(horizontal: 3),
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: i == _page
                                  ? AppColors.primary
                                  : AppColors.border,
                            ),
                          ),
                      ],
                    ),
                  ),
                  FilledButton(
                    onPressed: last ? _finish : () => _go(1),
                    child: Text(context.tr(last ? 'onb.start' : 'onb.next')),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
