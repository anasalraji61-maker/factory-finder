import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(unreadTotalProvider).valueOrNull ?? 0;
    return Scaffold(
      body: navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: navigationShell.currentIndex,
        onDestinationSelected: (i) {
          if (i == 2) ref.invalidate(unreadTotalProvider);
          navigationShell.goBranch(
            i,
            initialLocation: i == navigationShell.currentIndex,
          );
        },
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.explore_outlined),
            selectedIcon: const Icon(Icons.explore),
            label: context.tr('nav.discover'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.request_quote_outlined),
            selectedIcon: const Icon(Icons.request_quote),
            label: context.tr('nav.requests'),
          ),
          NavigationDestination(
            icon: _badged(unread, const Icon(Icons.chat_bubble_outline)),
            selectedIcon: _badged(unread, const Icon(Icons.chat_bubble)),
            label: context.tr('nav.messages'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.local_shipping_outlined),
            selectedIcon: const Icon(Icons.local_shipping),
            label: context.tr('nav.logistics'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            selectedIcon: const Icon(Icons.person),
            label: context.tr('nav.profile'),
          ),
        ],
      ),
    );
  }

  /// Unread count on the Messages tab icon (hidden at zero).
  Widget _badged(int count, Widget icon) {
    if (count <= 0) return icon;
    return Badge(
      key: const ValueKey<String>('nav-messages-badge'),
      label: Text(count > 99 ? '99+' : '$count'),
      child: icon,
    );
  }
}
