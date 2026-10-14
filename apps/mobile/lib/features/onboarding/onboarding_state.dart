import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Role chosen during onboarding.
enum UserRole { buyer, supplier }

/// Currencies offered during onboarding (all have mock FX rates).
const List<String> kOnboardingCurrencies = [
  'USD', 'IQD', 'EUR', 'CNY', 'TRY', 'AED', 'SAR', 'GBP',
];

/// True once the first-run flow was finished or skipped. Persisted by
/// `settingsPersistenceProvider`; `main` seeds it from storage and starts on
/// `/onboarding` only when unset. Tests start on `/discover`.
final onboardingCompletedProvider = StateProvider<bool>((ref) => false);

final userRoleProvider = StateProvider<UserRole>((ref) => UserRole.buyer);
