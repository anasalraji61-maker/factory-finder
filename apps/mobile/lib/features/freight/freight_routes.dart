import 'package:factory_finder/features/freight/screens/apply_forwarder_screen.dart';
import 'package:factory_finder/features/freight/screens/create_request_screen.dart';
import 'package:factory_finder/features/freight/screens/forwarder_request_screen.dart';
import 'package:factory_finder/features/freight/screens/freight_home_screen.dart';
import 'package:factory_finder/features/freight/screens/request_detail_screen.dart';
import 'package:go_router/go_router.dart';

/// `/logistics/freight` and its sub-routes. Mounted as a child of the
/// `/logistics` route (see `module_b.dart`).
final GoRoute freightRoute = GoRoute(
  path: 'freight',
  builder: (context, state) => const FreightHomeScreen(),
  routes: [
    GoRoute(
      path: 'new',
      builder: (context, state) => const CreateFreightRequestScreen(),
    ),
    GoRoute(
      path: 'requests/:id',
      builder: (context, state) =>
          FreightRequestDetailScreen(requestId: state.pathParameters['id'] ?? ''),
    ),
    GoRoute(
      path: 'forwarder/apply',
      builder: (context, state) => const ApplyForwarderScreen(),
    ),
    GoRoute(
      path: 'forwarder/requests/:id',
      builder: (context, state) =>
          ForwarderRequestScreen(requestId: state.pathParameters['id'] ?? ''),
    ),
  ],
);
