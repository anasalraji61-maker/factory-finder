import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/auth_bootstrap.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/router/auth_gate.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/features/onboarding/intro_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  registerFeatureStrings();

  KeyValueStore prefs;
  KeyValueStore secure;
  try {
    prefs = await SharedPrefsStore.open();
    secure = SecureTokenStore();
  } catch (_) {
    prefs = MemoryStore();
    secure = MemoryStore();
  }
  final settings = await PersistedSettings.load(prefs);
  // Installs that finished the older first-run flow never see the intro.
  final introDone = settings.onboardingDone || await loadIntroDone(prefs);

  final container = ProviderContainer(overrides: [
    keyValueStoreProvider.overrideWithValue(prefs),
    secureStoreProvider.overrideWithValue(secure),
    ...settings.overrides(),
    introDoneProvider.overrideWith((ref) => introDone),
  ]);
  final router = createAppRouter(
    showOnboarding: !settings.onboardingDone,
    auth: AuthGate.fromContainer(container),
  );

  runApp(UncontrolledProviderScope(
    container: container,
    child: FactoryFinderApp(router: router),
  ));
  restoreSessionOnStart(container);
}
