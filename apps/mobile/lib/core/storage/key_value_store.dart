import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Minimal async string store. Implementations: [SharedPrefsStore] (settings),
/// [SecureTokenStore] (secrets), [MemoryStore] (tests / default).
abstract class KeyValueStore {
  Future<String?> get(String key);
  Future<void> set(String key, String value);
  Future<void> remove(String key);
}

/// In-memory store. Default for providers so tests never touch plugins.
class MemoryStore implements KeyValueStore {
  MemoryStore([Map<String, String>? initial])
      : data = <String, String>{...?initial};

  final Map<String, String> data;

  @override
  Future<String?> get(String key) async => data[key];

  @override
  Future<void> set(String key, String value) async => data[key] = value;

  @override
  Future<void> remove(String key) async => data.remove(key);
}

/// Non-sensitive settings on top of shared_preferences.
class SharedPrefsStore implements KeyValueStore {
  SharedPrefsStore(this._prefs);

  final SharedPreferences _prefs;

  static Future<SharedPrefsStore> open() async =>
      SharedPrefsStore(await SharedPreferences.getInstance());

  @override
  Future<String?> get(String key) async => _prefs.getString(key);

  @override
  Future<void> set(String key, String value) async {
    await _prefs.setString(key, value);
  }

  @override
  Future<void> remove(String key) async {
    await _prefs.remove(key);
  }
}

/// Tokens only (Keychain / Android Keystore via flutter_secure_storage).
class SecureTokenStore implements KeyValueStore {
  SecureTokenStore([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<String?> get(String key) => _storage.read(key: key);

  @override
  Future<void> set(String key, String value) =>
      _storage.write(key: key, value: value);

  @override
  Future<void> remove(String key) => _storage.delete(key: key);
}

/// Settings store. Defaults to memory; `main` overrides with [SharedPrefsStore].
final keyValueStoreProvider =
    Provider<KeyValueStore>((ref) => MemoryStore());

/// Secret store (refresh token). Defaults to memory; `main` overrides.
final secureStoreProvider = Provider<KeyValueStore>((ref) => MemoryStore());
