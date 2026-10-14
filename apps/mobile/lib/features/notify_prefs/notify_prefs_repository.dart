import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class NotifyPrefsRepository {
  Future<NotifyPrefs> get();
  Future<NotifyPrefs> save(NotifyPrefs prefs);
}

class LiveNotifyPrefsRepository implements NotifyPrefsRepository {
  LiveNotifyPrefsRepository(this._api);
  final ApiClient _api;

  @override
  Future<NotifyPrefs> get() async =>
      NotifyPrefs.fromJson(await _api.get('/v1/notification-prefs'));

  @override
  Future<NotifyPrefs> save(NotifyPrefs prefs) async => NotifyPrefs.fromJson(
        await _api.put('/v1/notification-prefs', body: prefs.toUpdateJson()),
      );
}

class MockNotifyPrefsRepository implements NotifyPrefsRepository {
  NotifyPrefs _prefs = const NotifyPrefs(
    channels: {
      'price_drop': {'in_app', 'push'},
      'below_target': {'in_app', 'push', 'email'},
      'cheaper_equivalent': {'in_app'},
      'back_in_stock': {'in_app', 'push'},
      'new_results': {'in_app'},
    },
    quietStart: '22:00',
    quietEnd: '07:00',
    language: 'ar',
  );

  @override
  Future<NotifyPrefs> get() async {
    await mockDelay(150);
    return _prefs;
  }

  @override
  Future<NotifyPrefs> save(NotifyPrefs prefs) async {
    await mockDelay(150);
    _prefs = prefs;
    return _prefs;
  }
}

final notifyPrefsRepositoryProvider = Provider<NotifyPrefsRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockNotifyPrefsRepository() : LiveNotifyPrefsRepository(api);
});
