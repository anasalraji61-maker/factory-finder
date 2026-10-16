import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Store key set once the 3-page intro was finished or skipped.
const String kIntroDoneKey = 'onboarding.v1.done';

/// True once the intro was seen. Default is false (a fresh install); `main`
/// seeds it from storage, tests that bypass the gate override it to true.
final introDoneProvider = StateProvider<bool>((ref) => false);

/// Reads the persisted flag. Storage errors count as "not done".
Future<bool> loadIntroDone(KeyValueStore store) async {
  try {
    return await store.get(kIntroDoneKey) == '1';
  } catch (_) {
    return false;
  }
}

/// Marks the intro as seen: flips the provider at once (so the router gate
/// opens) and persists best-effort.
Future<void> markIntroDone(WidgetRef ref) async {
  ref.read(introDoneProvider.notifier).state = true;
  try {
    await ref.read(keyValueStoreProvider).set(kIntroDoneKey, '1');
  } catch (_) {
    // Persistence is best-effort; the intro may show once more next launch.
  }
}
