import 'package:factory_finder/features/feed/screens/composer_screen.dart';
import 'package:factory_finder/features/feed/screens/feed_screen.dart';
import 'package:factory_finder/features/feed/screens/muted_suppliers_screen.dart';
import 'package:factory_finder/features/feed/screens/post_detail_screen.dart';
import 'package:factory_finder/features/feed/screens/supplier_posts_screen.dart';
import 'package:go_router/go_router.dart';

export 'package:factory_finder/features/feed/feed_strings.dart' show feedStrings;
export 'package:factory_finder/features/feed/screens/feed_screen.dart' show FeedEntryButton;
export 'package:factory_finder/features/feed/widgets/follow_button.dart' show FollowButton;

/// Full-screen feed routes (registered from a module's `overlayRoutes`).
final List<RouteBase> feedRoutes = <RouteBase>[
  GoRoute(path: '/feed', builder: (context, state) => const FeedScreen()),
  GoRoute(path: '/feed/new', builder: (context, state) => const ComposerScreen()),
  GoRoute(path: '/feed/muted', builder: (context, state) => const MutedSuppliersScreen()),
  GoRoute(
    path: '/feed/post/:id',
    builder: (context, state) => PostDetailScreen(postId: state.pathParameters['id']!),
  ),
  GoRoute(
    path: '/feed/supplier/:id',
    builder: (context, state) => SupplierPostsScreen(supplierId: state.pathParameters['id']!),
  ),
];
