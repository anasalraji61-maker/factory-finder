import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Role chosen during onboarding.
enum UserRole { buyer, supplier }

/// Currencies offered during onboarding (all have mock FX rates).
const List<String> kOnboardingCurrencies = [
  'USD', 'IQD', 'EUR', 'CNY', 'TRY', 'AED', 'SAR', 'GBP',
];

/// True once the first-run flow was finished or skipped.
///
/// The app has no persistence layer (tokens, server URL and settings are
/// memory-only), so this is NOT stored on disk: onboarding shows once per
/// app launch. `main` starts the app on `/onboarding`; tests start on
/// `/discover` and never see it.
final onboardingCompletedProvider = StateProvider<bool>((ref) => false);

final userRoleProvider = StateProvider<UserRole>((ref) => UserRole.buyer);
