import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/features/onboarding/intro_state.dart';
import 'package:factory_finder/features/onboarding/onboarding_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

/// First-run intro: three pages, language toggle, Skip, page indicator.
/// Shown once before everything else (see `appRedirect`), and again from
/// Settings > About when [replay] is true.
class IntroScreen extends ConsumerStatefulWidget {
  const IntroScreen({super.key, this.replay = false});

  final bool replay;

  @override
  ConsumerState<IntroScreen> createState() => _IntroScreenState();
}

class _IntroScreenState extends ConsumerState<IntroScreen> {
  static const int _pageCount = 3;

  final PageController _pages = PageController();
  int _page = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    await markIntroDone(ref);
    if (!mounted) return;
    final router = GoRouter.of(context);
    if (widget.replay) {
      if (router.canPop()) {
        router.pop();
      } else {
        router.go('/discover');
      }
      return;
    }
    // The preferences/role flow still follows on a fresh install.
    router.go(ref.read(onboardingCompletedProvider) ? '/discover' : '/onboarding');
  }

  void _next() {
    _pages.nextPage(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
    );
  }

  void _toggleLanguage() {
    final notifier = ref.read(localeProvider.notifier);
    notifier.state = notifier.state.languageCode == 'ar'
        ? const Locale('en')
        : const Locale('ar');
  }

  Widget _page0() => const _IntroPage(
        icon: Icons.search,
        titleKey: 'intro.p1.title',
        bodyKey: 'intro.p1.body',
      );

  Widget _page1(BuildContext context) {
    Widget step(IconData icon, String key) => Padding(
          padding: const EdgeInsets.only(top: AppSpacing.md),
          child: Row(
            children: [
              Icon(icon, color: AppColors.accent),
              const SizedBox(width: AppSpacing.md),
              Expanded(child: Text(context.tr(key))),
            ],
          ),
        );
    return _IntroPage(
      icon: Icons.local_shipping_outlined,
      titleKey: 'intro.p2.title',
      bodyKey: 'intro.p2.body',
      extra: [
        const SizedBox(height: AppSpacing.md),
        Chip(
          key: const ValueKey<String>('intro-estimate-chip'),
          avatar: const Icon(Icons.info_outline, size: 18),
          label: Text(context.tr('intro.p2.estimate')),
        ),
        step(Icons.warehouse_outlined, 'intro.p2.step1'),
        step(Icons.directions_boat_outlined, 'intro.p2.step2'),
        step(Icons.receipt_long_outlined, 'intro.p2.step3'),
        step(Icons.home_outlined, 'intro.p2.step4'),
        const SizedBox(height: AppSpacing.md),
        Text(
          context.tr('intro.p2.estimate_note'),
          key: const ValueKey<String>('intro-estimate-note'),
          style: Theme.of(context)
              .textTheme
              .bodySmall
              ?.copyWith(color: AppColors.secondaryOf(context)),
        ),
      ],
    );
  }

  Widget _page2() => const _IntroPage(
        icon: Icons.verified_user_outlined,
        titleKey: 'intro.p3.title',
        bodyKey: 'intro.p3.body',
      );

  @override
  Widget build(BuildContext context) {
    final last = _page == _pageCount - 1;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
              child: Row(
                children: [
                  TextButton.icon(
                    key: const ValueKey<String>('intro-lang'),
                    onPressed: _toggleLanguage,
                    icon: const Icon(Icons.language, size: 18),
                    label: Text(context.tr('intro.lang_toggle')),
                  ),
                  const Spacer(),
                  TextButton(
                    key: const ValueKey<String>('intro-skip'),
                    onPressed: _finish,
                    child: Text(context.tr('intro.skip')),
                  ),
                ],
              ),
            ),
            Expanded(
              child: PageView(
                controller: _pages,
                onPageChanged: (i) => setState(() => _page = i),
                children: [_page0(), _page1(context), _page2()],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                children: [
                  Semantics(
                    label: context.tr('intro.page_of', {
                      'n': '${_page + 1}',
                      'total': '$_pageCount',
                    }),
                    child: ExcludeSemantics(
                      child: Row(
                        key: const ValueKey<String>('intro-dots'),
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          for (var i = 0; i < _pageCount; i++)
                            AnimatedContainer(
                              duration: const Duration(milliseconds: 200),
                              width: i == _page ? 20 : 8,
                              height: 8,
                              margin: const EdgeInsets.symmetric(horizontal: 3),
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(4),
                                color: i == _page
                                    ? AppColors.primary
                                    : AppColors.border,
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  SizedBox(
                    width: double.infinity,
                    child: last
                        ? FilledButton(
                            key: const ValueKey<String>('intro-start'),
                            onPressed: _finish,
                            child: Text(context.tr('intro.start')),
                          )
                        : FilledButton(
                            key: const ValueKey<String>('intro-next'),
                            onPressed: _next,
                            child: Text(context.tr('intro.next')),
                          ),
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

class _IntroPage extends StatelessWidget {
  const _IntroPage({
    required this.icon,
    required this.titleKey,
    required this.bodyKey,
    this.extra = const <Widget>[],
  });

  final IconData icon;
  final String titleKey;
  final String bodyKey;
  final List<Widget> extra;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: AppSpacing.lg),
          Icon(icon, size: 72, color: AppColors.primary),
          const SizedBox(height: AppSpacing.lg),
          Semantics(
            header: true,
            child: Text(
              context.tr(titleKey),
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w900),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            context.tr(bodyKey),
            style: TextStyle(
              height: 1.5,
              color: AppColors.secondaryOf(context),
            ),
          ),
          ...extra,
        ],
      ),
    );
  }
}
